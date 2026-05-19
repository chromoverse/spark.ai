"""SchedulerService — background 30s poll loop for due tasks."""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.path.manager import PathManager
from app.services.scheduler.models import ScheduledTask
from app.services.scheduler.persistence import SchedulerStore
from app.services.scheduler.trigger_handler import TriggerHandler
from app.utils.time_parser import cron_next_run, parse_datetime

logger = logging.getLogger(__name__)


class SchedulerService:
    def __init__(self):
        db_path = PathManager().layout.db_dir / "scheduler.db"
        self.store = SchedulerStore(db_path)
        self.handler = TriggerHandler()
        self._running = False
        self._poll_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("Scheduler started (30s poll)")

    async def stop(self) -> None:
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        self.store.close()
        logger.info("Scheduler stopped")

    async def schedule_reminder(
        self, user_id: str, label: str, trigger_at: datetime, text: Optional[str] = None,
    ) -> ScheduledTask:
        now = datetime.now(timezone.utc)
        task = ScheduledTask(
            id=uuid.uuid4().hex[:12],
            user_id=user_id,
            task_type="reminder",
            label=label,
            trigger_at=trigger_at.isoformat(),
            next_run_at=trigger_at.isoformat(),
            notification_text=text or label,
            created_at=now.isoformat(),
        )
        self.store.add(task)
        return task

    async def schedule_recurring(
        self, user_id: str, label: str, cron_expr: str, task_plan: Optional[list] = None,
    ) -> ScheduledTask:
        now = datetime.now(timezone.utc)
        next_run = cron_next_run(cron_expr, now)
        task = ScheduledTask(
            id=uuid.uuid4().hex[:12],
            user_id=user_id,
            task_type="recurring",
            label=label,
            cron_expression=cron_expr,
            next_run_at=next_run.isoformat() if next_run else None,
            task_plan=task_plan,
            notification_text=label,
            created_at=now.isoformat(),
        )
        self.store.add(task)
        return task

    async def _poll_loop(self) -> None:
        while self._running:
            await asyncio.sleep(30)
            try:
                now_iso = datetime.now(timezone.utc).isoformat()
                due_tasks = self.store.list_due(now_iso)
                for task in due_tasks:
                    await self._trigger(task)
            except Exception as exc:
                logger.error("Scheduler poll error: %s", exc)

    async def _trigger(self, task: ScheduledTask) -> None:
        try:
            if task.task_type == "reminder":
                await self.handler.fire_reminder(task)
            else:
                await self.handler.fire_recurring(task)
        except Exception as exc:
            logger.error("Trigger failed for %s: %s", task.id, exc)

        # Compute next run
        now = datetime.now(timezone.utc)
        next_at: Optional[str] = None
        if task.cron_expression:
            nxt = cron_next_run(task.cron_expression, now)
            next_at = nxt.isoformat() if nxt else None

        self.store.update_after_run(task.id, now.isoformat(), next_at)
