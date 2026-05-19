from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class ScheduledTask:
    id: str
    user_id: str
    task_type: str  # "reminder" | "recurring" | "one_shot"
    label: str
    cron_expression: Optional[str] = None
    trigger_at: Optional[str] = None  # ISO datetime
    task_plan: Optional[List[Dict[str, Any]]] = None
    notification_text: Optional[str] = None
    enabled: bool = True
    created_at: str = ""
    last_run_at: Optional[str] = None
    next_run_at: Optional[str] = None
    run_count: int = 0
