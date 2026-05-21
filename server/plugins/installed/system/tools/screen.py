"""Screen lock tool."""
import sys
import subprocess
from typing import Dict, Any
from datetime import datetime

from app.plugins.tools.tool_base import BaseTool, ToolOutput


class LockScreenTool(BaseTool):
    """Lock the OS screen immediately."""

    TOOL_DESCRIPTION = "Lock the OS screen immediately"
    EXECUTION_TARGET = "client"
    PARAMS_SCHEMA: Dict[str, Any] = {"delay_seconds": {"type": "integer", "required": False, "default": 0, "description": "Wait N seconds before locking (0 = immediate)"}}
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {"locked": {"type": "boolean"}, "locked_at": {"type": "string"}, "platform": {"type": "string"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "lock my screen"}]
    SEMANTIC_TAGS = ["system", "lock", "screen"]
    TOOL_CATEGORY = "system_control"

    def get_tool_name(self) -> str:
        return "lock_screen"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        delay = self.get_input(inputs, "delay_seconds", 0)
        try:
            if delay > 0:
                import asyncio
                await asyncio.sleep(delay)
            platform = sys.platform
            await self._lock(platform)
            return ToolOutput(success=True, data={"locked": True, "locked_at": datetime.now().isoformat(), "platform": platform})
        except Exception as e:
            return ToolOutput(success=False, data={}, error=str(e))

    async def _lock(self, platform: str) -> None:
        if platform == "win32":
            import ctypes
            ctypes.windll.user32.LockWorkStation()
        elif platform == "darwin":
            try:
                await self._run_subprocess(["pmset", "displaysleepnow"], check=True, timeout=5)
            except Exception:
                await self._run_subprocess(["osascript", "-e", 'tell application "System Events" to keystroke "q" using {command down, control down}'], check=True, timeout=5)
        elif platform.startswith("linux"):
            for cmd in [["loginctl", "lock-session"], ["xdg-screensaver", "lock"], ["gnome-screensaver-command", "-l"], ["i3lock"], ["slock"]]:
                try:
                    await self._run_subprocess(cmd, check=True, timeout=5)
                    return
                except (FileNotFoundError, subprocess.CalledProcessError):
                    continue
            raise RuntimeError("No lock tool found")
        else:
            raise RuntimeError(f"Unsupported platform: {platform}")


__all__ = ["LockScreenTool"]
