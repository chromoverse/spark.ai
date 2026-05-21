"""Agent runtime status tool.

agent_status:
- Purpose: fetch the current capability snapshot for the runtime/user.
- Inputs: user_id? (normally inferred from tool context)
- Outputs: capability snapshot fields plus checked_at.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from app.plugins.tools.tool_base import BaseTool, ToolOutput


class AgentStatusTool(BaseTool):
    """Return the current capability snapshot for the active user/runtime.

    Inputs:
    - user_id (string, optional): explicit user id, usually injected by the runtime

    Outputs:
    - capability snapshot fields from the capability service
    - checked_at (string): ISO timestamp for when the snapshot was fetched
    """

    # ── Plugin-shipped tool metadata ────────────────────────────────────
    TOOL_DESCRIPTION = "Get current status of the agent"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA: Dict[str, Any] = {}
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {
            "user_id": {"type": "string"},
            "environment": {"type": "string"},
            "runtime": {"type": "object"},
            "models_loaded": {"type": "array"},
            "limitations": {"type": "array"},
            "checked_at": {"type": "string"},
        },
        "error": {"type": "string"},
    }
    EXAMPLES = [
        {"user_utterance": "what is your current status"},
    ]
    SEMANTIC_TAGS = ["agent", "status", "runtime", "capabilities"]
    TOOL_CATEGORY = "spark_internal"

    def get_tool_name(self) -> str:
        return "agent_status"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        from app.agent.runtime.capability_service import get_capability_service

        user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "system").strip() or "system"
        snapshot = await get_capability_service().get_capability_snapshot(user_id=user_id)
        snapshot["checked_at"] = datetime.now().isoformat()
        return ToolOutput(success=True, data=snapshot)


__all__ = ["AgentStatusTool"]
