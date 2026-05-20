"""
Spark in-app control tools — manage the Spark desktop window and UI.

These emit socket events that the Electron main process handles.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from app.socket.utils import socket_emit
from ..base import BaseTool, ToolOutput


SPARK_CONTROL_EVENT = "spark:control"


class SparkWindowOpenTool(BaseTool):
    """Show/open the Spark main window.

    Inputs: none
    Outputs: action (string), success (boolean)
    """

    def get_tool_name(self) -> str:
        return "spark_window_open"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "").strip()
        delivered = await socket_emit(SPARK_CONTROL_EVENT, {"action": "window_open"}, user_id=user_id)
        return ToolOutput(success=delivered, data={"action": "window_open"}, error=None if delivered else "User not connected")


class SparkWindowCloseTool(BaseTool):
    """Hide/close the Spark main window.

    Inputs: none
    Outputs: action (string), success (boolean)
    """

    def get_tool_name(self) -> str:
        return "spark_window_close"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "").strip()
        delivered = await socket_emit(SPARK_CONTROL_EVENT, {"action": "window_close"}, user_id=user_id)
        return ToolOutput(success=delivered, data={"action": "window_close"}, error=None if delivered else "User not connected")


class SparkNavigateTool(BaseTool):
    """Navigate to a specific tab/page in the Spark main window.

    Inputs:
    - tab (string, required): one of history, spark-logs, tools, plugins, skills, permissions, settings

    Outputs: action (string), tab (string)
    """

    def get_tool_name(self) -> str:
        return "spark_navigate"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "").strip()
        tab = str(self.get_input(inputs, "tab", "") or "").strip().lower()
        if not tab:
            return ToolOutput(success=False, data={}, error="Missing required parameter: tab")

        delivered = await socket_emit(SPARK_CONTROL_EVENT, {"action": "navigate", "tab": tab}, user_id=user_id)
        return ToolOutput(success=delivered, data={"action": "navigate", "tab": tab}, error=None if delivered else "User not connected")


class SparkStorageOpenTool(BaseTool):
    """Open the Spark artifacts/storage folder in the file explorer.

    Inputs: none
    Outputs: path (string)
    """

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
