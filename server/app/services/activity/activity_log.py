from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import List

from app.kernel.contracts.models import KernelEvent
from app.kernel.eventing.event_bus import get_kernel_event_bus
from app.path.manager import PathManager
from app.services.activity.models import ActivityEntry
from app.services.activity.store import ActivityStore

logger = logging.getLogger(__name__)

_LOGGABLE_EVENTS = {"task_completed", "task_failed"}


class ActivityLog:
    """Central activity log — records tool executions and conversations."""

    def __init__(self):
        db_path = PathManager().layout.db_dir / "activity.db"
        self.store = ActivityStore(db_path)

    def subscribe_to_kernel(self) -> None:
        get_kernel_event_bus().subscribe(self._on_kernel_event)
        logger.info("ActivityLog subscribed to KernelEventBus")

    async def _on_kernel_event(self, event: KernelEvent) -> None:
        if event.event_type not in _LOGGABLE_EVENTS:
            return
        try:
            self.store.insert(ActivityEntry(
                id=uuid.uuid4().hex,
                user_id=event.user_id,
                session_id=event.session_id or event.request_id or "",
                entry_type="tool_execution",
                timestamp=event.timestamp,
                tool_name=event.tool_name,
                result_summary=self._summarize(event),
                success=event.status == "completed",
                metadata=event.payload,
                tags=self._extract_tags(event),
            ))
        except Exception as exc:
            logger.debug("ActivityLog insert failed: %s", exc)

    def log_conversation(self, user_id: str, session_id: str, query: str, response: str) -> None:
        self.store.insert(ActivityEntry(
            id=uuid.uuid4().hex,
            user_id=user_id,
            session_id=session_id,
            entry_type="conversation",
            timestamp=datetime.now(timezone.utc).isoformat(),
            query=query,
            result_summary=response[:300],
            success=True,
            tags=query.lower().split()[:10],
        ))

    def search(self, user_id: str, query: str, limit: int = 20) -> List[ActivityEntry]:
        return self.store.search(user_id, query, limit)

    def get_recent(self, user_id: str, limit: int = 50) -> List[ActivityEntry]:
        return self.store.get_recent(user_id, limit)

    def close(self) -> None:
        self.store.close()

    @staticmethod
    def _summarize(event: KernelEvent) -> str:
        tool = event.tool_name or "unknown"
        status = event.status or event.event_type
        msg = event.payload.get("message", "") if event.payload else ""
        return f"{tool}: {status}" + (f" — {msg[:100]}" if msg else "")

    @staticmethod
    def _extract_tags(event: KernelEvent) -> List[str]:
        tags = []
        if event.tool_name:
            tags.append(event.tool_name)
        if event.payload:
            for key in ("file_path", "query", "label", "app_name"):
                val = event.payload.get(key)
                if val:
                    tags.append(str(val).split("/")[-1].split("\\")[-1])
        return tags
