from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from app.kernel.contracts.models import KernelEvent
from app.utils.path_manager import PathManager

logger = logging.getLogger(__name__)


@dataclass
class KernelLogQueryResult:
    logs: list[dict[str, Any]]
    next_cursor: int
    trimmed: bool
    startup_id: str


class KernelLogIndex:
    """
    User-scoped log index using startup JSONL file.

    - Writes structured entries as events arrive.
    - Tracks user_id -> line offsets for capped reads.
    """

    def __init__(self):
        self.startup_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        logs_dir = PathManager().get_logs_dir()
        self.log_file = logs_dir / f"server-{self.startup_id}.jsonl"

        self._user_offsets: dict[str, list[int]] = {}

        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.log_file.touch(exist_ok=True)

    async def record_event(self, event: KernelEvent) -> None:
        record = {
            "timestamp": event.timestamp,
            "level": "INFO",
            "module": "kernel.event_bus",
            "message": event.event_type,
            "user_id": event.user_id,
            "request_id": event.request_id,
            "session_id": event.session_id,
            "startup_id": self.startup_id,
            "task_id": event.task_id,
            "tool_name": event.tool_name,
            "status": event.status,
            "payload": event.payload,
        }

        line = json.dumps(record, ensure_ascii=True) + "\n"
        with self.log_file.open("a+", encoding="utf-8") as f:
            f.seek(0, 2)
            offset = f.tell()
            f.write(line)

        self._user_offsets.setdefault(event.user_id, []).append(offset)

    async def query_user_logs(
        self,
        user_id: str,
        level: Optional[str] = None,
        cursor: int = 0,
        limit: int = 100,
        max_bytes: int = 32_000,
    ) -> KernelLogQueryResult:
        offsets = self._user_offsets.get(user_id, [])
        if not offsets:
            return KernelLogQueryResult([], cursor, False, self.startup_id)

        slice_offsets = offsets[cursor : cursor + limit]
        if not slice_offsets:
            return KernelLogQueryResult([], cursor, False, self.startup_id)

        logs: list[dict[str, Any]] = []
        total_bytes = 0

        with self.log_file.open("r", encoding="utf-8") as f:
            for offset in slice_offsets:
                f.seek(offset)
                line = f.readline()
                if not line:
                    continue
                entry = json.loads(line)
                if level and str(entry.get("level", "")).upper() != level.upper():
                    continue

                size = len(line.encode("utf-8"))
                if total_bytes + size > max_bytes:
                    return KernelLogQueryResult(
                        logs=logs,
                        next_cursor=cursor + len(logs),
                        trimmed=True,
                        startup_id=self.startup_id,
                    )

                total_bytes += size
                logs.append(entry)

        return KernelLogQueryResult(
            logs=logs,
            next_cursor=cursor + len(slice_offsets),
            trimmed=False,
            startup_id=self.startup_id,
        )


_log_index: KernelLogIndex | None = None


def get_kernel_log_index() -> KernelLogIndex:
    global _log_index
    if _log_index is None:
        _log_index = KernelLogIndex()
    return _log_index


