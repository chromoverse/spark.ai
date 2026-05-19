"""schedule_task tool — schedule a recurring task with cron expression."""
from __future__ import annotations

from typing import Any, Dict

from ..base import BaseTool, ToolOutput


class ScheduleTaskTool(BaseTool):
    """Schedule a recurring task.

    Inputs:
    - label (string, required): description of the recurring task
    - schedule (string, required): cron expression or natural language like "every morning"
    - task_plan (array, optional): pre-built task JSON array to re-execute

    Outputs:
    - task_id (string)
    - cron_expression (string)
    - next_run_at (string)
    - label (string)
    """

    def get_tool_name(self) -> str:
        return "schedule_task"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        label = self.get_input(inputs, "label", "")
        schedule_raw = self.get_input(inputs, "schedule", "")
        task_plan = self.get_input(inputs, "task_plan", None)
        user_id = str(inputs.get("_user_id") or "guest").strip() or "guest"

        if not label:
            return ToolOutput(success=False, data={}, error="label is required")
        if not schedule_raw:
            return ToolOutput(success=False, data={}, error="schedule is required")

        from app.utils.time_parser import parse_cron
        cron_expr = parse_cron(schedule_raw)
        if not cron_expr:
            return ToolOutput(success=False, data={}, error=f"Could not parse schedule: {schedule_raw}")

        from app.services.scheduler import get_scheduler_service
        task = await get_scheduler_service().schedule_recurring(
            user_id=user_id, label=label, cron_expr=cron_expr, task_plan=task_plan,
        )

        return ToolOutput(success=True, data={
            "task_id": task.id,
            "cron_expression": task.cron_expression or "",
            "next_run_at": task.next_run_at or "",
            "label": task.label,
        })


__all__ = ["ScheduleTaskTool"]
