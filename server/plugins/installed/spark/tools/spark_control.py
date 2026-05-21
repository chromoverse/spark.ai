"""Spark in-app control tools — manage the Spark desktop window and UI.

These emit socket events that the Electron main process handles.
"""
from __future__ import annotations

from typing import Any, Dict

from app.plugins.tools.tool_base import BaseTool, ToolOutput


SPARK_CONTROL_EVENT = "spark:control"


async def _emit(payload: dict, user_id: str) -> bool:
    from app.socket.utils import socket_emit
    return await socket_emit(SPARK_CONTROL_EVENT, payload, user_id=user_id)


class SparkWindowOpenTool(BaseTool):
    """Show/open the Spark main window."""

    TOOL_DESCRIPTION = "Show/open the Spark main window"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA: Dict[str, Any] = {}
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {"action": {"type": "string"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "open your window", "inputs": {}}]
    SEMANTIC_TAGS = ["spark", "window", "open", "show"]
    TOOL_CATEGORY = "spark_internal"

    def get_tool_name(self) -> str:
        return "spark_window_open"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "").strip()
        delivered = await _emit({"action": "window_open"}, user_id=user_id)
        return ToolOutput(success=delivered, data={"action": "window_open"}, error=None if delivered else "User not connected")


class SparkWindowCloseTool(BaseTool):
    """Hide/close the Spark main window."""

    TOOL_DESCRIPTION = "Hide/close the Spark main window"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA: Dict[str, Any] = {}
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {"action": {"type": "string"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "close your window", "inputs": {}}]
    SEMANTIC_TAGS = ["spark", "window", "close", "hide"]
    TOOL_CATEGORY = "spark_internal"

    def get_tool_name(self) -> str:
        return "spark_window_close"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "").strip()
        delivered = await _emit({"action": "window_close"}, user_id=user_id)
        return ToolOutput(success=delivered, data={"action": "window_close"}, error=None if delivered else "User not connected")


class SparkNavigateTool(BaseTool):
    """Navigate to a specific tab in the Spark main window."""

    TOOL_DESCRIPTION = "Navigate to a specific tab in the Spark main window (history, spark-logs, tools, plugins, skills, permissions, settings)"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA: Dict[str, Any] = {
        "tab": {"type": "string", "required": True, "description": "Tab name: history, spark-logs, tools, plugins, skills, permissions, settings"},
    }
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {"action": {"type": "string"}, "tab": {"type": "string"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "open logs tab", "inputs": {"tab": "spark-logs"}}]
    SEMANTIC_TAGS = ["spark", "navigate", "tab", "logs", "tools", "settings"]
    TOOL_CATEGORY = "spark_internal"

    def get_tool_name(self) -> str:
        return "spark_navigate"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "").strip()
        tab = str(self.get_input(inputs, "tab", "") or "").strip().lower()
        if not tab:
            return ToolOutput(success=False, data={}, error="Missing required parameter: tab")
        delivered = await _emit({"action": "navigate", "tab": tab}, user_id=user_id)
        return ToolOutput(success=delivered, data={"action": "navigate", "tab": tab}, error=None if delivered else "User not connected")


class SparkStorageOpenTool(BaseTool):
    """Open the Spark artifacts/storage folder in file explorer."""

    TOOL_DESCRIPTION = "Open the Spark artifacts/storage folder in file explorer. Use when user says open your storage or your folder."
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA: Dict[str, Any] = {}
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {"path": {"type": "string"}, "action": {"type": "string"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "open your storage folder", "inputs": {}}]
    SEMANTIC_TAGS = ["spark", "storage", "folder", "artifacts", "open"]
    TOOL_CATEGORY = "spark_internal"

    def get_tool_name(self) -> str:
        return "spark_storage_open"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        import asyncio, os, subprocess, sys
        from app.path.manager import PathManager

        pm = PathManager()
        artifacts_dir = pm.get_artifacts_dir()
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        path = str(artifacts_dir)

        def _open():
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])

        await asyncio.to_thread(_open)
        return ToolOutput(success=True, data={"path": path, "action": "storage_open"})


__all__ = [
    "SparkWindowOpenTool",
    "SparkWindowCloseTool",
    "SparkNavigateTool",
    "SparkStorageOpenTool",
]
