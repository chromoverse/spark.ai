"""set_reminder tool — schedule a one-shot reminder notification."""
from __future__ import annotations

from typing import Any, Dict

from ..base import BaseTool, ToolOutput


class SetReminderTool(BaseTool):
    """Set a reminder that fires at a specific time.

    Inputs:
    - label (string, required): what to remind about
    - trigger_at (string, required): time expression e.g. "6pm today", "in 30 minutes"
    - notification_text (string, optional)

    Outputs:
    - task_id (string)
    - trigger_at (string)
    - label (string)
    """

    def get_tool_name(self) -> str:
        return "set_reminder"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        label = self.get_input(inputs, "label", "")
        trigger_at_raw = self.get_input(inputs, "trigger_at", "")
        notification_text = self.get_input(inputs, "notification_text", None)
        user_id = str(inputs.get("_user_id") or "guest").strip() or "guest"

        if not label:
            return ToolOutput(success=False, data={}, error="label is required")
        if not trigger_at_raw:
            return ToolOutput(success=False, data={}, error="trigger_at is required")

        from app.utils.time_parser import parse_datetime
        trigger_dt = parse_datetime(trigger_at_raw)
        if not trigger_dt:
            return ToolOutput(success=False, data={}, error=f"Could not parse time: {trigger_at_raw}")

        from app.services.scheduler import get_scheduler_service
        task = await get_scheduler_service().schedule_reminder(
            user_id=user_id, label=label, trigger_at=trigger_dt,
            text=notification_text or label,
        )

        return ToolOutput(success=True, data={
            "task_id": task.id,
            "trigger_at": task.next_run_at or task.trigger_at or "",
            "label": task.label,
        })


__all__ = ["SetReminderTool"]
