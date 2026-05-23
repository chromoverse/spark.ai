from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from app.agent.execution_gateway import get_orchestrator

# Default output field policy per tool.
# `include_full=True` can still return the complete payload on demand.
_TOOL_OUTPUT_POLICIES: Dict[str, Dict[str, List[str]]] = {
    "ai_summarize": {
        "default_fields": [
            "summary",
            "formatted_content",
            "original_length",
            "summary_length",
            "summarized_at",
        ],
    },
    "web_research": {
        # Intent-aware fields. Delivery layer simply forwards whatever the
        # tool returned for the active intent — no field is required here.
        "default_fields": [
            "intent",
            "result_type",
            "sources",
            # entity intents
            "entities",
            "actions",
            # research intent
            "scraped_content",
            "text",
            # factual_lookup intent
            "snippets",
        ],
    },
}


def _json_safe(value: Any) -> Any:
    """Convert values to JSON-safe shapes for socket payloads."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


class ToolOutputDeliveryService:
    """
    Centralized tool output retrieval for UI.

    Tools should not emit socket events directly. Instead, execution state keeps
    full outputs and UI can request details only when needed.
    """

    def _pick_task(
        self,
        user_id: str,
        task_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        job_id: Optional[str] = None,
    ):
        orchestrator = get_orchestrator()

        if task_id:
            # Search ALL job states — orchestrator.get_task does cross-state lookup
            return orchestrator.get_task(user_id, task_id, job_id=job_id)

        # No task_id: gather candidates across ALL states for this user
        all_states = orchestrator.get_all_states_for_user(user_id)
        if not all_states:
            state = orchestrator.get_state(user_id)
            if state:
                all_states = {"_": state}
            else:
                return None

        candidates = []
        for state in all_states.values():
            candidates.extend(state.tasks.values())

        if tool_name:
            candidates = [t for t in candidates if t.tool == tool_name]

        if not candidates:
            return None

        # Latest finished task wins.
        candidates.sort(
            key=lambda t: (
                t.completed_at or t.created_at,
                t.task_id,
            ),
            reverse=True,
        )
        return candidates[0]

    @staticmethod
    def _select_data_fields(
        tool_name: str,
        raw_data: Dict[str, Any],
        include_full: bool,
        fields: Optional[List[str]],
    ) -> Dict[str, Any]:
        if include_full:
            selected_keys = list(raw_data.keys())
        elif fields:
            selected_keys = [k for k in fields if k in raw_data]
        else:
            policy = _TOOL_OUTPUT_POLICIES.get(tool_name, {})
            default_fields = policy.get("default_fields", [])
            if default_fields:
                selected_keys = [k for k in default_fields if k in raw_data]
            else:
                selected_keys = list(raw_data.keys())[:6]

        return {k: _json_safe(raw_data.get(k)) for k in selected_keys}

    async def list_outputs(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        orchestrator = get_orchestrator()
        all_states = orchestrator.get_all_states_for_user(user_id)
        if not all_states:
            state = orchestrator.get_state(user_id)
            if state:
                all_states = {"_": state}
            else:
                return []

        all_tasks = []
        for state in all_states.values():
            all_tasks.extend(state.tasks.values())

        all_tasks.sort(
            key=lambda t: (t.completed_at or t.created_at, t.task_id),
            reverse=True,
        )

        outputs: List[Dict[str, Any]] = []
        for task in all_tasks:
            if task.status not in {"completed", "failed"}:
                continue
            data = task.output.data if task.output and isinstance(task.output.data, dict) else {}
            outputs.append(
                {
                    "task_id": task.task_id,
                    "tool": task.tool,
                    "status": task.status,
                    "completed_at": _json_safe(task.completed_at),
                    "duration_ms": task.duration_ms,
                    "available_fields": list(data.keys()),
                }
            )
            if len(outputs) >= max(1, limit):
                break

        return outputs

    async def get_output(
        self,
        user_id: str,
        task_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        include_full: bool = False,
        fields: Optional[List[str]] = None,
        job_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        task = self._pick_task(user_id=user_id, task_id=task_id, tool_name=tool_name, job_id=job_id)
        if not task:
            return None

        raw_data = task.output.data if task.output and isinstance(task.output.data, dict) else {}
        selected_data = self._select_data_fields(
            tool_name=task.tool,
            raw_data=raw_data,
            include_full=include_full,
            fields=fields,
        )

        # Get job_id for frontend correlation
        orchestrator = get_orchestrator()
        state = orchestrator._find_state_for_task(user_id, task.task_id, job_id=job_id)
        resolved_job_id = state.execution_id if state else job_id

        return {
            "user_id": user_id,
            "task_id": task.task_id,
            "job_id": resolved_job_id,
            "tool": task.tool,
            "status": task.status,
            "duration_ms": task.duration_ms,
            "error": task.error or (task.output.error if task.output else None),
            "available_fields": list(raw_data.keys()),
            "data": selected_data,
        }


_tool_output_delivery_service: Optional[ToolOutputDeliveryService] = None


def get_tool_output_delivery_service() -> ToolOutputDeliveryService:
    global _tool_output_delivery_service
    if _tool_output_delivery_service is None:
        _tool_output_delivery_service = ToolOutputDeliveryService()
    return _tool_output_delivery_service
