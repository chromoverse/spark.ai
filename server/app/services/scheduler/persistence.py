"""SQLite-backed storage for scheduled tasks."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from app.services.scheduler.models import ScheduledTask


class SchedulerStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_table()

    def _ensure_table(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_tasks (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                task_type TEXT NOT NULL,
                label TEXT NOT NULL,
                cron_expression TEXT,
                trigger_at TEXT,
                task_plan TEXT,
                notification_text TEXT,
                enabled INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                last_run_at TEXT,
                next_run_at TEXT,
                run_count INTEGER DEFAULT 0
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_next_run ON scheduled_tasks(next_run_at)")
        self._conn.commit()

    def add(self, task: ScheduledTask) -> None:
        self._conn.execute(
            """INSERT INTO scheduled_tasks
               (id, user_id, task_type, label, cron_expression, trigger_at, task_plan,
                notification_text, enabled, created_at, last_run_at, next_run_at, run_count)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (task.id, task.user_id, task.task_type, task.label,
             task.cron_expression, task.trigger_at,
             json.dumps(task.task_plan) if task.task_plan else None,
             task.notification_text, int(task.enabled), task.created_at,
             task.last_run_at, task.next_run_at, task.run_count),
        )
        self._conn.commit()

    def get(self, task_id: str) -> Optional[ScheduledTask]:
        row = self._conn.execute(
            "SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        return self._row_to_task(row) if row else None

    def list_for_user(self, user_id: str) -> List[ScheduledTask]:
        rows = self._conn.execute(
            "SELECT * FROM scheduled_tasks WHERE user_id = ? AND enabled = 1", (user_id,)
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def list_due(self, before: str) -> List[ScheduledTask]:
        """Return enabled tasks whose next_run_at <= before (ISO string)."""
        rows = self._conn.execute(
            "SELECT * FROM scheduled_tasks WHERE enabled = 1 AND next_run_at IS NOT NULL AND next_run_at <= ?",
            (before,),
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def update_after_run(self, task_id: str, ran_at: str, next_at: Optional[str]) -> None:
        self._conn.execute(
            """UPDATE scheduled_tasks
               SET last_run_at = ?, next_run_at = ?, run_count = run_count + 1,
                   enabled = CASE WHEN ? IS NULL THEN 0 ELSE enabled END
               WHERE id = ?""",
            (ran_at, next_at, next_at, task_id),
        )
        self._conn.commit()

    def delete(self, task_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _row_to_task(row: tuple) -> ScheduledTask:
        return ScheduledTask(
            id=row[0], user_id=row[1], task_type=row[2], label=row[3],
            cron_expression=row[4], trigger_at=row[5],
            task_plan=json.loads(row[6]) if row[6] else None,
            notification_text=row[7], enabled=bool(row[8]),
            created_at=row[9], last_run_at=row[10],
            next_run_at=row[11], run_count=row[12],
        )
