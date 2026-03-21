import logging
import time
<<<<<<< HEAD
import sqlite3
from typing import Optional, List, Dict, Any
from collections import OrderedDict
=======
from typing import Optional, List, Dict, Any
from collections import OrderedDict
import sqlite3
>>>>>>> 7ff3f566494ef823f1013bcd9bc269d63d0fb839

logger = logging.getLogger(__name__)

_MSG_CACHE_MAX_USERS = 50   # max users held in the in-process message LRU


class LocalKVManager:
    """
    SQLite storage for the desktop environment.

    Two logical stores
    ──────────────────
    kv_store  – generic key/value pairs (embeddings, user details, etc.)
    messages  – ordered conversation history

    Performance choices
    ───────────────────
    • Single persistent connection (no per-call open/close overhead)
    • WAL journal mode: concurrent reads, ~10× faster writes vs default rollback journal
    • In-process LRU message cache: sub-microsecond reads for hot users
    """

    _instance: Optional["LocalKVManager"] = None
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
        db_path = PathManager().get_user_data_dir() / "db" / "kvstore.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # check_same_thread=False is safe here because all coroutines run on the
        # same event-loop thread and we never share the connection across threads.
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=10)
        self._init_db()

        # In-process LRU: {user_id: [message_dicts]}
        self._msg_cache: OrderedDict[str, List[Dict[str, Any]]] = OrderedDict()

        logger.info("LocalKVManager initialised at %s (WAL mode)", db_path)

    # ──────────────────────────────────────────────
    # Schema
    # ──────────────────────────────────────────────

    def _init_db(self) -> None:
        cur = self._conn.cursor()

        # WAL mode + sensible performance pragmas
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA cache_size=-8000")  # 8 MB in-process page cache
        cur.execute("PRAGMA temp_store=MEMORY")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS kv_store (
                key    TEXT PRIMARY KEY,
                value  TEXT NOT NULL,
                expiry REAL
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id         TEXT PRIMARY KEY,
                user_id    TEXT NOT NULL,
                role       TEXT NOT NULL,
                content    TEXT NOT NULL,
                timestamp  TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        """)
<<<<<<< HEAD

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_messages
            ON messages (user_id, created_at DESC)
=======
        self._ensure_messages_sync_columns(cursor)

        # Create index for fast user queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_messages 
            ON messages(user_id, created_at DESC)
>>>>>>> 7ff3f566494ef823f1013bcd9bc269d63d0fb839
        """)
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_user_messages_sync
            ON messages(user_id, is_synced, created_at DESC)
            """
        )

        self._conn.commit()

<<<<<<< HEAD
    # ──────────────────────────────────────────────
    # In-process LRU helpers
    # ──────────────────────────────────────────────

    def _cache_get(self, user_id: str) -> Optional[List[Dict[str, Any]]]:
=======
    def _ensure_messages_sync_columns(self, cursor: sqlite3.Cursor) -> None:
        """Backfill sync-tracking columns for existing databases."""
        cursor.execute("PRAGMA table_info(messages)")
        existing_columns = {str(row[1]) for row in cursor.fetchall()}
        if "is_synced" not in existing_columns:
            cursor.execute(
                "ALTER TABLE messages ADD COLUMN is_synced INTEGER NOT NULL DEFAULT 0"
            )
        if "synced_at" not in existing_columns:
            cursor.execute("ALTER TABLE messages ADD COLUMN synced_at REAL")
    
    async def ping(self):
        """Health check"""
        return True
    
    # ============ IN-MEMORY CACHE HELPERS ============
    
    def _invalidate_msg_cache(self, user_id: str):
        """Remove user from message cache (call on writes)"""
>>>>>>> 7ff3f566494ef823f1013bcd9bc269d63d0fb839
        if user_id in self._msg_cache:
            self._msg_cache.move_to_end(user_id)
            return self._msg_cache[user_id]
        return None

    def _cache_set(self, user_id: str, messages: List[Dict[str, Any]]) -> None:
        self._msg_cache[user_id] = messages
        self._msg_cache.move_to_end(user_id)
        while len(self._msg_cache) > _MSG_CACHE_MAX_USERS:
            self._msg_cache.popitem(last=False)

    def _cache_invalidate(self, user_id: str) -> None:
        self._msg_cache.pop(user_id, None)

    # ──────────────────────────────────────────────
    # Generic KV store
    # ──────────────────────────────────────────────

    async def get(self, key: str) -> Optional[str]:
        try:
            cur = self._conn.cursor()
            cur.execute("SELECT value, expiry FROM kv_store WHERE key = ?", (key,))
            row = cur.fetchone()
            if not row:
                return None
            value, expiry = row
            if expiry is not None and expiry < time.time():
                await self.delete(key)
                return None
            return value
        except Exception as exc:
            logger.error("KV get error: %s", exc)
            return None

    async def set(self, key: str, value: str, ex: Optional[int] = None) -> bool:
        try:
            expiry = time.time() + ex if ex else None
            self._conn.execute(
                "INSERT OR REPLACE INTO kv_store (key, value, expiry) VALUES (?, ?, ?)",
                (key, value, expiry),
            )
            self._conn.commit()
            return True
        except Exception as exc:
            logger.error("KV set error: %s", exc)
            return False

    async def delete(self, *keys: str) -> bool:
        if not keys:
            return False
        try:
            ph = ",".join("?" * len(keys))
            self._conn.execute(f"DELETE FROM kv_store WHERE key IN ({ph})", keys)
            self._conn.commit()
            return True
        except Exception as exc:
            logger.error("KV delete error: %s", exc)
            return False

    async def scan(self, match: Optional[str] = None, count: int = 100) -> List[str]:
        """Return up to `count` keys matching the optional glob pattern."""
        try:
            cur = self._conn.cursor()
            if match:
                cur.execute(
                    "SELECT key FROM kv_store WHERE key LIKE ? LIMIT ?",
                    (match.replace("*", "%"), count),
                )
            else:
                cur.execute("SELECT key FROM kv_store LIMIT ?", (count,))
            return [row[0] for row in cur.fetchall()]
        except Exception as exc:
            logger.error("KV scan error: %s", exc)
            return []

    # ──────────────────────────────────────────────
    # Message store
    # ──────────────────────────────────────────────

    async def add_message(
        self,
        user_id: str,
        role: str,
        content: str,
        timestamp: str,
        message_id: str,
<<<<<<< HEAD
=======
        is_synced: bool = False,
>>>>>>> 7ff3f566494ef823f1013bcd9bc269d63d0fb839
    ) -> bool:
        """Append one message row. Invalidates the in-process cache."""
        try:
<<<<<<< HEAD
            self._conn.execute(
                "INSERT INTO messages (id, user_id, role, content, timestamp, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (message_id, user_id, role, content, timestamp, time.time()),
=======
            now_ts = time.time()
            synced_flag = 1 if bool(is_synced) else 0
            synced_at = now_ts if synced_flag else None
            cursor = self._conn.cursor()
            cursor.execute(
                """
                INSERT INTO messages (id, user_id, role, content, timestamp, created_at, is_synced, synced_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (message_id, user_id, role, content, timestamp, now_ts, synced_flag, synced_at)
>>>>>>> 7ff3f566494ef823f1013bcd9bc269d63d0fb839
            )
            self._conn.commit()
            self._cache_invalidate(user_id)
            return True
        except Exception as exc:
            logger.error("SQLite add_message error: %s", exc)
            return False

<<<<<<< HEAD
=======
    async def get_unsynced_message_count(self, user_id: str) -> int:
        """Return how many local messages are still pending cloud sync."""
        try:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM messages
                WHERE user_id = ? AND is_synced = 0
                """,
                (user_id,),
            )
            row = cursor.fetchone()
            return int(row[0] if row else 0)
        except Exception as e:
            logger.error(f"SQLite unsynced count error: {e}")
            return 0

    async def get_users_with_unsynced_messages(self) -> List[str]:
        """List users that currently have unsynced local messages."""
        try:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                SELECT DISTINCT user_id
                FROM messages
                WHERE is_synced = 0
                ORDER BY user_id ASC
                """
            )
            rows = cursor.fetchall()
            return [str(row[0]) for row in rows if row and row[0]]
        except Exception as e:
            logger.error(f"SQLite unsynced users lookup error: {e}")
            return []

    async def mark_messages_synced(self, user_id: str, message_ids: List[str]) -> int:
        """Mark specific messages as synced after a successful cloud push."""
        try:
            cleaned_ids = [str(mid) for mid in message_ids if mid]
            if not cleaned_ids:
                return 0
            cursor = self._conn.cursor()
            placeholders = ",".join("?" for _ in cleaned_ids)
            params = [time.time(), user_id, *cleaned_ids]
            cursor.execute(
                f"""
                UPDATE messages
                SET is_synced = 1, synced_at = ?
                WHERE user_id = ? AND id IN ({placeholders})
                """,
                tuple(params),
            )
            updated = int(cursor.rowcount or 0)
            self._conn.commit()
            return updated
        except Exception as e:
            logger.error(f"SQLite mark messages synced error: {e}")
            return 0
    
>>>>>>> 7ff3f566494ef823f1013bcd9bc269d63d0fb839
    async def get_messages(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Return the `limit` most recent messages in chronological order (oldest first).
        Checks the in-process cache before hitting disk.
        """
        # ── In-process cache hit ────────────────────────────────────────────
        cached = self._cache_get(user_id)
        if cached is not None:
            return cached[-limit:] if len(cached) > limit else cached

        # ── Disk read ───────────────────────────────────────────────────────
        try:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT id, role, content, timestamp
                FROM messages
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            )
            rows = cur.fetchall()
            if not rows:
                return []

            # Rows are newest-first from the DB; reverse to chronological order
            messages = [
                {"id": r[0], "role": r[1], "content": r[2], "timestamp": r[3]}
                for r in reversed(rows)
            ]
            self._cache_set(user_id, messages)
            return messages
        except Exception as exc:
            logger.error("SQLite get_messages error: %s", exc)
            return []

    async def clear_messages(self, user_id: str) -> bool:
        """Delete all messages for a user and evict the in-process cache."""
        try:
            self._conn.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
            self._conn.commit()
            self._cache_invalidate(user_id)
            return True
        except Exception as exc:
            logger.error("SQLite clear_messages error: %s", exc)
            return False

<<<<<<< HEAD
    async def ping(self) -> bool:
        return True
=======
    # ============ SYNC OUTBOX METHODS ============

    async def enqueue_sync_event(self, scope: str, op: str, key: str, payload_json: str) -> int:
        """Persist a sync event for background cloud flush."""
        try:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                INSERT INTO sync_outbox (scope, op, key, payload_json, created_at, attempts, last_error)
                VALUES (?, ?, ?, ?, ?, 0, NULL)
                """,
                (scope, op, key, payload_json, time.time()),
            )
            self._conn.commit()
            return int(cursor.lastrowid or 0)
        except Exception as e:
            logger.error(f"LocalKV enqueue sync event error: {e}")
            return 0

    async def upsert_sync_event(self, scope: str, op: str, key: str, payload_json: str) -> int:
        """
        Keep only the latest pending event for a given (scope, key) pair.
        This avoids unbounded outbox growth for high-frequency writes.
        """
        try:
            cursor = self._conn.cursor()
            cursor.execute(
                "DELETE FROM sync_outbox WHERE scope = ? AND key = ?",
                (scope, key),
            )
            cursor.execute(
                """
                INSERT INTO sync_outbox (scope, op, key, payload_json, created_at, attempts, last_error)
                VALUES (?, ?, ?, ?, ?, 0, NULL)
                """,
                (scope, op, key, payload_json, time.time()),
            )
            self._conn.commit()
            return int(cursor.lastrowid or 0)
        except Exception as e:
            logger.error(f"LocalKV upsert sync event error: {e}")
            return 0

    async def fetch_sync_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Fetch oldest pending sync events."""
        try:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                SELECT id, scope, op, key, payload_json, created_at, attempts, last_error
                FROM sync_outbox
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            )
            rows = cursor.fetchall()
            return [
                {
                    "id": int(row[0]),
                    "scope": str(row[1]),
                    "op": str(row[2]),
                    "key": str(row[3]),
                    "payload_json": str(row[4]),
                    "created_at": float(row[5]),
                    "attempts": int(row[6]),
                    "last_error": row[7],
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"LocalKV fetch sync events error: {e}")
            return []

    async def mark_sync_events_success(self, ids: List[int]) -> int:
        """Delete successfully flushed sync events."""
        try:
            if not ids:
                return 0
            cursor = self._conn.cursor()
            placeholders = ",".join("?" for _ in ids)
            cursor.execute(
                f"DELETE FROM sync_outbox WHERE id IN ({placeholders})",
                tuple(ids),
            )
            deleted = int(cursor.rowcount or 0)
            self._conn.commit()
            return deleted
        except Exception as e:
            logger.error(f"LocalKV mark sync success error: {e}")
            return 0

    async def mark_sync_event_failure(self, event_id: int, error: str) -> None:
        """Increment attempts and store last error for a failed event."""
        try:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                UPDATE sync_outbox
                SET attempts = attempts + 1, last_error = ?
                WHERE id = ?
                """,
                (error[:1000], int(event_id)),
            )
            self._conn.commit()
        except Exception as e:
            logger.error(f"LocalKV mark sync failure error: {e}")

    async def get_sync_outbox_size(self) -> int:
        """Return number of pending sync events."""
        try:
            cursor = self._conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM sync_outbox")
            row = cursor.fetchone()
            return int(row[0] if row else 0)
        except Exception as e:
            logger.error(f"LocalKV sync outbox size error: {e}")
            return 0
>>>>>>> 7ff3f566494ef823f1013bcd9bc269d63d0fb839
