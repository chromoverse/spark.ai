"""SparkAI runtime path tools.

spark_data_open:
- Purpose: open the local SparkAI user-data directory.
- Inputs: none.
- Outputs: data_dir, requested_data_dir, using_fallback_dir, opened_with, opened_at.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from typing import Any, Dict

from app.path.manager import PathManager

from ..base import BaseTool, ToolOutput


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
    """Open the local SparkAI user-data directory.

    Inputs:
    - none

    Outputs:
    - data_dir (string): resolved active SparkAI data directory
    - requested_data_dir (string): preferred primary directory before fallback selection
    - using_fallback_dir (boolean): whether runtime is using `.sparkai_data` fallback storage
    - opened_with (string): app used to open the directory
    - opened_at (string): ISO timestamp for the open action
    """

    def get_tool_name(self) -> str:
        return "spark_data_open"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        path_manager = PathManager()
        data_dir = path_manager.get_user_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)

        opened_with = _open_path(str(data_dir))
        return ToolOutput(
            success=True,
            data={
                "data_dir": str(data_dir),
                "requested_data_dir": str(path_manager.get_requested_user_data_dir()),
                "using_fallback_dir": path_manager.is_using_fallback_user_data_dir(),
                "opened_with": opened_with,
                "opened_at": datetime.now().isoformat(),
            },
        )


__all__ = ["SparkDataOpenTool"]
