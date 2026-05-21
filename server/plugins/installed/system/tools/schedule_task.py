"""schedule_task tool."""
from __future__ import annotations
from typing import Any, Dict
from app.plugins.tools.tool_base import BaseTool, ToolOutput


class ScheduleTaskTool(BaseTool):
    """Schedule a recurring task with a cron expression or natural language."""

    TOOL_DESCRIPTION = "Schedule a recurring task with a cron expression or natural language schedule"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA: Dict[str, Any] = {
        "label": {"type": "string", "required": True},
        "schedule": {"type": "string", "required": True, "description": "Cron expression or natural language like 'every morning', 'daily', 'every Monday'"},
        "task_plan": {"type": "array", "required": False, "description": "Pre-built task JSON array to re-execute on schedule"},
    }
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {"task_id": {"type": "string"}, "cron_expression": {"type": "string"}, "next_run_at": {"type": "string"}, "label": {"type": "string"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "run the backup script every night at midnight", "inputs": {"label": "Run backup script", "schedule": "every night"}}]
    SEMANTIC_TAGS = ["schedule", "recurring", "cron", "periodic", "automation"]
    TOOL_CATEGORY = "automation"

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
        task = await get_scheduler_service().schedule_recurring(user_id=user_id, label=label, cron_expr=cron_expr, task_plan=task_plan)
        return ToolOutput(success=True, data={"task_id": task.id, "cron_expression": task.cron_expression or "", "next_run_at": task.next_run_at or "", "label": task.label})


__all__ = ["ScheduleTaskTool"]
