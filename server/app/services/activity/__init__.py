from __future__ import annotations

from app.services.activity.activity_log import ActivityLog

_instance: ActivityLog | None = None


def get_activity_log() -> ActivityLog:
    global _instance
    if _instance is None:
        _instance = ActivityLog()
    return _instance
