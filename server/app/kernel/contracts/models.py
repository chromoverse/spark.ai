from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass
class KernelEvent:
    event_type: str
    user_id: str
    request_id: Optional[str] = None
    session_id: Optional[str] = None
    task_id: Optional[str] = None
    tool_name: Optional[str] = None
    status: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "user_id": self.user_id,
            "request_id": self.request_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "tool_name": self.tool_name,
            "status": self.status,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }

