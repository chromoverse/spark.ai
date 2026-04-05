"""Agent runtime status tool.

agent_status:
- Purpose: fetch the current capability snapshot for the runtime/user.
- Inputs: user_id? (normally inferred from tool context)
- Outputs: capability snapshot fields plus checked_at.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from ..base import BaseTool, ToolOutput


class AgentStatusTool(BaseTool):
    """Return the current capability snapshot for the active user/runtime.

    Inputs:
    - user_id (string, optional): explicit user id, usually injected by the runtime

    Outputs:
    - capability snapshot fields from the capability service
    - checked_at (string): ISO timestamp for when the snapshot was fetched
    """

    def get_tool_name(self) -> str:
        return "agent_status"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        from app.agent.runtime.capability_service import get_capability_service

        user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "system").strip() or "system"
        snapshot = await get_capability_service().get_capability_snapshot(user_id=user_id)
        snapshot["checked_at"] = datetime.now().isoformat()
        return ToolOutput(success=True, data=snapshot)


__all__ = ["AgentStatusTool"]
