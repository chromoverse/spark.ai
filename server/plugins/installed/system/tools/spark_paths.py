"""SparkAI runtime path tools."""
from __future__ import annotations
import asyncio
import os
import subprocess
import sys
from datetime import datetime
from typing import Any, Dict
from app.path.manager import PathManager
from app.plugins.tools.tool_base import BaseTool, ToolOutput


def _open_path(path: str) -> str:
    if sys.platform == "win32":
        os.startfile(path)
        return "default"
    if sys.platform == "darwin":
        subprocess.Popen(["open", path])
        return "default"
    subprocess.Popen(["xdg-open", path])
    return "default"


class SparkDataOpenTool(BaseTool):
    """Open the local SparkAI user-data directory."""

    TOOL_DESCRIPTION = "Open the local SparkAI user-data directory in file explorer"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA: Dict[str, Any] = {}
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {"data_dir": {"type": "string"}, "requested_data_dir": {"type": "string"}, "using_fallback_dir": {"type": "boolean"}, "opened_with": {"type": "string"}, "opened_at": {"type": "string"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "open your data folder"}]
    SEMANTIC_TAGS = ["spark", "data", "folder", "open"]
    TOOL_CATEGORY = "spark_internal"

    def get_tool_name(self) -> str:
        return "spark_data_open"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        path_manager = PathManager()
        data_dir = path_manager.get_user_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        opened_with = await asyncio.to_thread(_open_path, str(data_dir))
        return ToolOutput(success=True, data={
            "data_dir": str(data_dir),
            "requested_data_dir": str(path_manager.get_requested_user_data_dir()),
            "using_fallback_dir": path_manager.is_using_fallback_user_data_dir(),
            "opened_with": opened_with,
            "opened_at": datetime.now().isoformat(),
        })


__all__ = ["SparkDataOpenTool"]
