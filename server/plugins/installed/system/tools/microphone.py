"""
Microphone control tools that signal the connected desktop client over socket.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from app.socket.utils import socket_emit

from app.plugins.tools.tool_base import BaseTool, ToolOutput


MIC_CONTROL_SOCKET_EVENT = "device:mic-control"


class _BaseMicControlTool(BaseTool):
    action: str = ""
    target_muted_state: bool = False

    async def _dispatch(self, inputs: Dict[str, Any]) -> ToolOutput:
        user_id_raw = inputs.get("_user_id") or inputs.get("user_id")
        user_id = str(user_id_raw or "").strip()

        if not user_id:
            return ToolOutput(
                success=False,
                data={},
                error="Missing required parameter: user_id",
            )

        action = self.action.strip().lower()
        requested_at = datetime.now(timezone.utc).isoformat()
        payload = {
            "action": action,
            "source": "tool",
            "requested_at": requested_at,
        }

        delivered = await socket_emit(
            MIC_CONTROL_SOCKET_EVENT,
            payload,
            user_id=user_id,
        )

        if not delivered:
            return ToolOutput(
                success=False,
                data={
                    "action": action,
                    "event": MIC_CONTROL_SOCKET_EVENT,
                    "requested_at": requested_at,
                    "user_id": user_id,
                },
                error=f"User '{user_id}' is not connected",
            )

        return ToolOutput(
            success=True,
            data={
                "action": action,
                "event": MIC_CONTROL_SOCKET_EVENT,
                "mic_muted": self.target_muted_state,
                "requested_at": requested_at,
                "user_id": user_id,
            },
        )


class MicMuteTool(_BaseMicControlTool):
    """Mute the microphone on the connected desktop client."""

    TOOL_DESCRIPTION = "Mute the microphone on the connected desktop client"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA: Dict[str, Any] = {}
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {
            "action": {"type": "string"},
            "event": {"type": "string"},
            "mic_muted": {"type": "boolean"},
            "requested_at": {"type": "string"},
            "user_id": {"type": "string"},
        },
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "mic mute"}]
    SEMANTIC_TAGS = ["system", "mic", "mute"]
    TOOL_CATEGORY = "system_control"

    action = "mute"
    target_muted_state = True

    def get_tool_name(self) -> str:
        return "mic_mute"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        return await self._dispatch(inputs)


class MicUnmuteTool(_BaseMicControlTool):
    """Unmute the microphone on the connected desktop client."""

    TOOL_DESCRIPTION = "Unmute the microphone on the connected desktop client"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA: Dict[str, Any] = {}
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {
            "action": {"type": "string"},
            "event": {"type": "string"},
            "mic_muted": {"type": "boolean"},
            "requested_at": {"type": "string"},
            "user_id": {"type": "string"},
        },
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "mic unmute"}]
    SEMANTIC_TAGS = ["system", "mic", "unmute"]
    TOOL_CATEGORY = "system_control"

    action = "unmute"
    target_muted_state = False

    def get_tool_name(self) -> str:
        return "mic_unmute"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        return await self._dispatch(inputs)


__all__ = [
    "MIC_CONTROL_SOCKET_EVENT",
    "MicMuteTool",
    "MicUnmuteTool",
]
