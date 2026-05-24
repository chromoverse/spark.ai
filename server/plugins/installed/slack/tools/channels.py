"""Slack channel tools."""
from __future__ import annotations
from typing import Any, Dict
from app.connectors.clients.slack import get_slack_client
from app.plugins.tools.tool_base import BaseTool, ToolOutput


class SlackChannelsTool(BaseTool):
    """
    List Slack channels the user has access to.

    Inputs:
    - user_id (string, required)
    - limit (integer, optional): Max channels (default: 30)

    Outputs:
    - channels (array): [{id, name, is_private, num_members}]
    """

    TOOL_DESCRIPTION = "List Slack channels accessible to the user"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA = {
        "user_id": {"type": "string", "required": True},
        "limit": {"type": "integer", "required": False, "default": 30},
    }
    OUTPUT_SCHEMA = {
        "success": {"type": "boolean"},
        "data": {"channels": {"type": "array"}, "total": {"type": "integer"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "show my slack channels"}]
    SEMANTIC_TAGS = ["slack", "channels", "list"]
    TOOL_CATEGORY = "communication"

    def get_tool_name(self) -> str:
        return "slack_channels"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            user_id = str(inputs.get("_user_id") or inputs.get("user_id"))
            client = await get_slack_client(user_id)
            limit = int(inputs.get("limit", 30))

            channels = await client.list_channels(limit=limit)
            result = [{
                "id": ch["id"],
                "name": ch["name"],
                "is_private": ch.get("is_private", False),
                "num_members": ch.get("num_members", 0),
            } for ch in channels]

            return ToolOutput(success=True, data={"channels": result, "total": len(result)})
        except Exception as exc:
            return ToolOutput(success=False, data={}, error=str(exc))
