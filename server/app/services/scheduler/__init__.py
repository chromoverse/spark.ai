from __future__ import annotations

from typing import Optional

from app.services.scheduler.scheduler_service import SchedulerService

_instance: Optional[SchedulerService] = None


def get_scheduler_service() -> SchedulerService:
    global _instance
    if _instance is None:
        _instance = SchedulerService()
    return _instance
