"""Slack messaging tools — read, send, search."""
from __future__ import annotations
from typing import Any, Dict
from app.connectors.clients.slack import get_slack_client
from app.plugins.tools.tool_base import BaseTool, ToolOutput


class SlackMessagesTool(BaseTool):
    """
    Read recent messages from a Slack channel.

    Inputs:
    - user_id (string, required)
    - channel_id (string, required)
    - limit (integer, optional): default 20

    Outputs:
    - messages (array): [{text, user, timestamp}]
    """

    TOOL_DESCRIPTION = "Read recent messages from a Slack channel"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA = {
        "user_id": {"type": "string", "required": True},
        "channel_id": {"type": "string", "required": True},
        "limit": {"type": "integer", "required": False, "default": 20},
    }
    OUTPUT_SCHEMA = {
        "success": {"type": "boolean"},
        "data": {"messages": {"type": "array"}, "total": {"type": "integer"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "read slack messages from general"}]
    SEMANTIC_TAGS = ["slack", "messages", "read", "channel"]
    TOOL_CATEGORY = "communication"

    def get_tool_name(self) -> str:
        return "slack_messages"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            user_id = str(inputs.get("_user_id") or inputs.get("user_id"))
            client = await get_slack_client(user_id)
            channel_id = inputs["channel_id"]
            limit = int(inputs.get("limit", 20))

            messages = await client.channel_history(channel_id, limit=limit)
            result = [{
                "text": m.get("text", ""),
                "user": m.get("user", ""),
                "timestamp": m.get("ts", ""),
            } for m in messages]

            return ToolOutput(success=True, data={"messages": result, "total": len(result)})
        except Exception as exc:
            return ToolOutput(success=False, data={}, error=str(exc))


class SlackSendTool(BaseTool):
    """
    Send a message to a Slack channel.

    Inputs:
    - user_id (string, required)
    - channel_id (string, required)
    - text (string, required)

    Outputs:
    - sent (boolean)
    - channel (string)
    - timestamp (string)
    """

    TOOL_DESCRIPTION = "Send a message to a Slack channel"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA = {
        "user_id": {"type": "string", "required": True},
        "channel_id": {"type": "string", "required": True},
        "text": {"type": "string", "required": True},
    }
    OUTPUT_SCHEMA = {
        "success": {"type": "boolean"},
        "data": {"sent": {"type": "boolean"}, "channel": {"type": "string"}, "timestamp": {"type": "string"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "send a message on slack"}]
    SEMANTIC_TAGS = ["slack", "send", "message", "post"]
    TOOL_CATEGORY = "communication"

    def get_tool_name(self) -> str:
        return "slack_send"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            user_id = str(inputs.get("_user_id") or inputs.get("user_id"))
            client = await get_slack_client(user_id)

            resp = await client.send_message(inputs["channel_id"], inputs["text"])
            return ToolOutput(success=True, data={
                "sent": True,
                "channel": resp.get("channel", ""),
                "timestamp": resp.get("ts", ""),
            })
        except Exception as exc:
            return ToolOutput(success=False, data={}, error=str(exc))


class SlackSearchTool(BaseTool):
    """
    Search Slack messages across all channels.

    Inputs:
    - user_id (string, required)
    - query (string, required)
    - count (integer, optional): default 20

    Outputs:
    - matches (array): [{text, channel_name, user, timestamp, permalink}]
    - total (integer)
    """

    TOOL_DESCRIPTION = "Search Slack messages across all accessible channels"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA = {
        "user_id": {"type": "string", "required": True},
        "query": {"type": "string", "required": True, "description": "Search query"},
        "count": {"type": "integer", "required": False, "default": 20},
    }
    OUTPUT_SCHEMA = {
        "success": {"type": "boolean"},
        "data": {"matches": {"type": "array"}, "total": {"type": "integer"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "search slack for deployment"}]
    SEMANTIC_TAGS = ["slack", "search", "find"]
    TOOL_CATEGORY = "communication"

    def get_tool_name(self) -> str:
        return "slack_search"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            user_id = str(inputs.get("_user_id") or inputs.get("user_id"))
            client = await get_slack_client(user_id)
            count = int(inputs.get("count", 20))

            matches = await client.search_messages(inputs["query"], count=count)
            result = [{
                "text": m.get("text", ""),
                "channel_name": m.get("channel", {}).get("name", ""),
                "user": m.get("username", ""),
                "timestamp": m.get("ts", ""),
                "permalink": m.get("permalink", ""),
            } for m in matches]

            return ToolOutput(success=True, data={"matches": result, "total": len(result)})
        except Exception as exc:
            return ToolOutput(success=False, data={}, error=str(exc))


__all__ = ["SlackMessagesTool", "SlackSendTool", "SlackSearchTool"]
