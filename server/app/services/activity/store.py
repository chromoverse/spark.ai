from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import List

from app.services.activity.models import ActivityEntry


class ActivityStore:
    """SQLite FTS5-backed storage for activity entries."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS activity (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                entry_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                tool_name TEXT,
                query TEXT,
                result_summary TEXT,
                success INTEGER DEFAULT 1,
                metadata TEXT,
                tags TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_activity_user ON activity(user_id);
            CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity(timestamp);
        """)
        # FTS5 virtual table for full-text search
        self._conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS activity_fts USING fts5(
                id UNINDEXED,
                user_id UNINDEXED,
                query,
                result_summary,
                tool_name,
                tags,
                content='activity',
                content_rowid='rowid'
            )
        """)
        self._conn.commit()

    def insert(self, entry: ActivityEntry) -> None:
        meta_json = json.dumps(entry.metadata) if entry.metadata else "{}"
        tags_str = " ".join(entry.tags)
        self._conn.execute(
            """INSERT INTO activity
               (id, user_id, session_id, entry_type, timestamp, tool_name, query, result_summary, success, metadata, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (entry.id, entry.user_id, entry.session_id, entry.entry_type,
             entry.timestamp, entry.tool_name, entry.query, entry.result_summary,
             int(entry.success), meta_json, tags_str),
        )
        self._conn.execute(
            """INSERT INTO activity_fts(rowid, id, user_id, query, result_summary, tool_name, tags)
               SELECT rowid, id, user_id, query, result_summary, tool_name, tags
               FROM activity WHERE id = ?""",
            (entry.id,),
        )
        self._conn.commit()

    def search(self, user_id: str, query: str, limit: int = 20) -> List[ActivityEntry]:
        safe_query = query.replace('"', '""')
        rows = self._conn.execute(
            """SELECT a.* FROM activity a
               JOIN activity_fts f ON a.rowid = f.rowid
               WHERE f.activity_fts MATCH ? AND a.user_id = ?
               ORDER BY a.timestamp DESC LIMIT ?""",
            (f'"{safe_query}"', user_id, limit),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def get_by_session(self, user_id: str, session_id: str) -> List[ActivityEntry]:
        rows = self._conn.execute(
            "SELECT * FROM activity WHERE user_id = ? AND session_id = ? ORDER BY timestamp",
            (user_id, session_id),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def get_recent(self, user_id: str, limit: int = 50) -> List[ActivityEntry]:
        rows = self._conn.execute(
            "SELECT * FROM activity WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _row_to_entry(row: tuple) -> ActivityEntry:
        return ActivityEntry(
            id=row[0],
            user_id=row[1],
            session_id=row[2],
            entry_type=row[3],
            timestamp=row[4],
            tool_name=row[5],
            query=row[6],
            result_summary=row[7],
            success=bool(row[8]),
            metadata=json.loads(row[9]) if row[9] else {},
            tags=row[10].split() if row[10] else [],
        )
