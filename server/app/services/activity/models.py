from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ActivityEntry:
    id: str
    user_id: str
    session_id: str
    entry_type: str  # "conversation" | "tool_execution" | "reminder" | "scheduled_task"
    timestamp: str
    tool_name: Optional[str] = None
    query: Optional[str] = None
    result_summary: str = ""
    success: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
