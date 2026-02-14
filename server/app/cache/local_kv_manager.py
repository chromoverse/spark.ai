import json
import logging
import time
from typing import Optional, List, Dict, Any
from pathlib import Path
import sqlite3
import asyncio

logger = logging.getLogger(__name__)


class LocalKVManager:
    """SQLite-based storage for desktop environment"""
    
    _instance: Optional['LocalKVManager'] = None
    _initialized: bool = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        # Prevent re-initialization if already initialized
        if LocalKVManager._initialized:
            return
        LocalKVManager._initialized = True
        
        from app.utils.path_manager import PathManager
        self.path_manager = PathManager()
        self.db_path = self.path_manager.get_user_data_dir() / "db" / "kvstore.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        logger.info(f"🗄️ Local SQLite Store initialized at {self.db_path}")
    
    def _init_db(self):
        """Initialize SQLite database"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
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
        
        conn.commit()
        conn.close()
    
    def _get_connection(self):
        """Get SQLite connection"""
        return sqlite3.connect(str(self.db_path))
    
    async def ping(self):
        """Health check"""
        return True
    
    # ============ KV STORE METHODS ============
    
    async def get(self, key: str) -> Optional[str]:
        """Get value by key"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT value, expiry FROM kv_store WHERE key = ?", (key,))
            row = cursor.fetchone()
            conn.close()
            
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
            
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute(
                "INSERT OR REPLACE INTO kv_store (key, value, expiry) VALUES (?, ?, ?)",
                (key, value, expiry)
            )
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"LocalKV Set Error: {e}")
            return False
    
    async def delete(self, *keys: str) -> bool:
        """Delete keys"""
        try:
            if not keys:
                return False
            
            conn = self._get_connection()
            cursor = conn.cursor()
            
            placeholders = ','.join('?' * len(keys))
            cursor.execute(f"DELETE FROM kv_store WHERE key IN ({placeholders})", keys)
            cursor.execute(f"DELETE FROM lists WHERE key IN ({placeholders})", keys)
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"LocalKV Delete Error: {e}")
            return False
    
    async def rpush(self, key: str, *values: str) -> bool:
        """Append to list"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT MAX(position) FROM lists WHERE key = ?", (key,))
            max_pos = cursor.fetchone()[0]
            start_pos = (max_pos + 1) if max_pos is not None else 0
            
            for i, value in enumerate(values):
                cursor.execute(
                    "INSERT INTO lists (key, value, position) VALUES (?, ?, ?)",
                    (key, value, start_pos + i)
                )
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"LocalKV RPush Error: {e}")
            return False
    
    async def lrange(self, key: str, start: int, end: int) -> List[str]:
        """Get list range"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT value FROM lists WHERE key = ? ORDER BY position",
                (key,)
            )
            
            rows = cursor.fetchall()
            conn.close()
            
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
            conn = self._get_connection()
            cur = conn.cursor()
            
            if match:
                pattern = match.replace('*', '%')
                cur.execute("SELECT key FROM kv_store WHERE key LIKE ? LIMIT ?", (pattern, count))
            else:
                cur.execute("SELECT key FROM kv_store LIMIT ?", (count,))
            
            rows = cur.fetchall()
            conn.close()
            
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
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute(
                """
                INSERT INTO messages (id, user_id, role, content, timestamp, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (message_id, user_id, role, content, timestamp, time.time())
            )
            
            conn.commit()
            conn.close()
            logger.debug(f"✅ SQLite: Added message {message_id}")
            return True
        except Exception as e:
            logger.error(f"SQLite Add Message Error: {e}")
            return False
    
    async def get_messages(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get last N messages for user from SQLite"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
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
            conn.close()
            
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
            
            logger.debug(f"📜 SQLite: Retrieved {len(messages)} messages for {user_id}")
            return messages
            
        except Exception as e:
            logger.error(f"SQLite Get Messages Error: {e}")
            return []
    
    async def clear_messages(self, user_id: str) -> bool:
        """Clear all messages for user"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
            deleted = cursor.rowcount
            
            conn.commit()
            conn.close()
            
            logger.info(f"🗑️ SQLite: Deleted {deleted} messages for {user_id}")
            return True
        except Exception as e:
            logger.error(f"SQLite Clear Messages Error: {e}")
            return False