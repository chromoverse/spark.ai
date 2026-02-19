import json
import logging
import time
from typing import Optional, List, Dict, Any
from pathlib import Path
from collections import OrderedDict
import sqlite3
import asyncio

logger = logging.getLogger(__name__)

# In-memory cache size per user
_MSG_CACHE_MAX_USERS = 50


class LocalKVManager:
    """
    SQLite-based storage for desktop environment.
    
    OPTIMIZED:
    - Single persistent connection (no per-call connect/close)
    - WAL journal mode for ~10x faster writes
    - In-memory LRU cache for messages (sub-microsecond reads)
    """
    
    _instance: Optional['LocalKVManager'] = None
    _initialized: bool = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if LocalKVManager._initialized:
            return
        LocalKVManager._initialized = True
        
        from app.utils.path_manager import PathManager
        self.path_manager = PathManager()
        self.db_path = self.path_manager.get_user_data_dir() / "db" / "kvstore.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # ✅ SINGLE persistent connection — no more per-call overhead
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,  # safe: we serialize via asyncio
            timeout=10
        )
        
        self._init_db()
        
        # ✅ In-memory message cache: {user_id: [messages]}
        self._msg_cache: OrderedDict[str, List[Dict[str, Any]]] = OrderedDict()
        
        logger.info(f"🗄️ Local SQLite Store initialized at {self.db_path} (WAL mode, persistent conn)")
    
    def _init_db(self):
        """Initialize SQLite database with performance pragmas"""
        cursor = self._conn.cursor()
        
        # ✅ WAL mode = concurrent reads + much faster writes
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA cache_size=-8000")  # 8MB cache
        cursor.execute("PRAGMA temp_store=MEMORY")
        
        # KV Store table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS kv_store (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                expiry REAL
            )
        """)
        
        # Lists table (for backward compat)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lists (
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                position INTEGER NOT NULL,
                PRIMARY KEY (key, position)
            )
        """)
        
        # Messages table - THE MAIN STORAGE
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        
        # Create index for fast user queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_messages 
            ON messages(user_id, created_at DESC)
        """)
        
        self._conn.commit()
    
    async def ping(self):
        """Health check"""
        return True
    
    # ============ IN-MEMORY CACHE HELPERS ============
    
    def _invalidate_msg_cache(self, user_id: str):
        """Remove user from message cache (call on writes)"""
        if user_id in self._msg_cache:
            del self._msg_cache[user_id]
    
    def _set_msg_cache(self, user_id: str, messages: List[Dict[str, Any]]):
        """Store messages in cache with LRU eviction"""
        self._msg_cache[user_id] = messages
        self._msg_cache.move_to_end(user_id)
        while len(self._msg_cache) > _MSG_CACHE_MAX_USERS:
            self._msg_cache.popitem(last=False)
    
    # ============ KV STORE METHODS ============
    
    async def get(self, key: str) -> Optional[str]:
        """Get value by key"""
        try:
            cursor = self._conn.cursor()
            cursor.execute("SELECT value, expiry FROM kv_store WHERE key = ?", (key,))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            value, expiry = row
            
            if expiry is not None and expiry < time.time():
                await self.delete(key)
                return None
            
            return value
        except Exception as e:
            logger.error(f"LocalKV Get Error: {e}")
            return None
    
    async def set(self, key: str, value: str, ex: Optional[int] = None) -> bool:
        """Set key-value pair"""
        try:
            expiry = time.time() + ex if ex else None
            cursor = self._conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO kv_store (key, value, expiry) VALUES (?, ?, ?)",
                (key, value, expiry)
            )
            self._conn.commit()
            return True
        except Exception as e:
            logger.error(f"LocalKV Set Error: {e}")
            return False
    
    async def delete(self, *keys: str) -> bool:
        """Delete keys"""
        try:
            if not keys:
                return False
            
            cursor = self._conn.cursor()
            placeholders = ','.join('?' * len(keys))
            cursor.execute(f"DELETE FROM kv_store WHERE key IN ({placeholders})", keys)
            cursor.execute(f"DELETE FROM lists WHERE key IN ({placeholders})", keys)
            self._conn.commit()
            return True
        except Exception as e:
            logger.error(f"LocalKV Delete Error: {e}")
            return False
    
    async def rpush(self, key: str, *values: str) -> bool:
        """Append to list"""
        try:
            cursor = self._conn.cursor()
            cursor.execute("SELECT MAX(position) FROM lists WHERE key = ?", (key,))
            max_pos = cursor.fetchone()[0]
            start_pos = (max_pos + 1) if max_pos is not None else 0
            
            for i, value in enumerate(values):
                cursor.execute(
                    "INSERT INTO lists (key, value, position) VALUES (?, ?, ?)",
                    (key, value, start_pos + i)
                )
            
            self._conn.commit()
            return True
        except Exception as e:
            logger.error(f"LocalKV RPush Error: {e}")
            return False
    
    async def lrange(self, key: str, start: int, end: int) -> List[str]:
        """Get list range"""
        try:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT value FROM lists WHERE key = ? ORDER BY position",
                (key,)
            )
            
            rows = cursor.fetchall()
            
            if not rows:
                return []
            
            values = [row[0] for row in rows]
            
            if end == -1:
                return values[start:]
            return values[start:end + 1]
        except Exception as e:
            logger.error(f"LocalKV LRange Error: {e}")
            return []
    
    async def scan(self, cursor: int = 0, match: Optional[str] = None, count: int = 100) -> tuple[int, List[str]]:
        """Scan keys"""
        try:
            cur = self._conn.cursor()
            
            if match:
                pattern = match.replace('*', '%')
                cur.execute("SELECT key FROM kv_store WHERE key LIKE ? LIMIT ?", (pattern, count))
            else:
                cur.execute("SELECT key FROM kv_store LIMIT ?", (count,))
            
            rows = cur.fetchall()
            keys = [row[0] for row in rows]
            return 0, keys
        except Exception as e:
            logger.error(f"LocalKV Scan Error: {e}")
            return 0, []
    
    # ============ MESSAGE STORAGE METHODS ============
    
    async def add_message(
        self, 
        user_id: str, 
        role: str, 
        content: str, 
        timestamp: str,
        message_id: str
    ) -> bool:
        """Add message to SQLite"""
        try:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                INSERT INTO messages (id, user_id, role, content, timestamp, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (message_id, user_id, role, content, timestamp, time.time())
            )
            self._conn.commit()
            
            # ✅ Invalidate cache so next get_messages() fetches fresh data
            self._invalidate_msg_cache(user_id)
            
            logger.debug(f"✅ SQLite: Added message {message_id}")
            return True
        except Exception as e:
            logger.error(f"SQLite Add Message Error: {e}")
            return False
    
    async def get_messages(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get last N messages for user from SQLite (with in-memory cache)"""
        try:
            # ✅ Check in-memory cache first (sub-microsecond)
            if user_id in self._msg_cache:
                cached = self._msg_cache[user_id]
                self._msg_cache.move_to_end(user_id)
                result = cached[-limit:] if len(cached) > limit else cached
                logger.debug(f"⚡ SQLite cache HIT: {len(result)} messages for {user_id}")
                return result
            
            # Cache miss — hit disk
            cursor = self._conn.cursor()
            cursor.execute(
                """
                SELECT id, role, content, timestamp
                FROM messages
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, limit)
            )
            
            rows = cursor.fetchall()
            
            if not rows:
                return []
            
            # Reverse to get chronological order (oldest first)
            messages = []
            for row in reversed(rows):
                messages.append({
                    "id": row[0],
                    "role": row[1],
                    "content": row[2],
                    "timestamp": row[3]
                })
            
            # ✅ Store in cache
            self._set_msg_cache(user_id, messages)
            
            logger.debug(f"📜 SQLite: Retrieved {len(messages)} messages for {user_id}")
            return messages
            
        except Exception as e:
            logger.error(f"SQLite Get Messages Error: {e}")
            return []
    
    async def clear_messages(self, user_id: str) -> bool:
        """Clear all messages for user"""
        try:
            cursor = self._conn.cursor()
            cursor.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
            deleted = cursor.rowcount
            self._conn.commit()
            
            # ✅ Invalidate cache
            self._invalidate_msg_cache(user_id)
            
            logger.info(f"🗑️ SQLite: Deleted {deleted} messages for {user_id}")
            return True
        except Exception as e:
            logger.error(f"SQLite Clear Messages Error: {e}")
            return False