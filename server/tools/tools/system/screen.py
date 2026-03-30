"""
Screen lock tool — locks the OS screen immediately.
"""

import sys
import subprocess
import logging
from typing import Dict, Any
from datetime import datetime

from ..base import BaseTool, ToolOutput


class LockScreenTool(BaseTool):
    """Lock the screen immediately.

    Inputs:
    - delay_seconds (int, optional) - wait N seconds before locking (default 0)

    Outputs:
    - locked (boolean)
    - locked_at (string)
    - platform (string)
    """

    def get_tool_name(self) -> str:
        return "lock_screen"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        delay = self.get_input(inputs, "delay_seconds", 0)

        try:
            if delay > 0:
                import asyncio
                await asyncio.sleep(delay)

            platform = sys.platform
            self._lock(platform)

            return ToolOutput(
                success=True,
                data={
                    "locked": True,
                    "locked_at": datetime.now().isoformat(),
                    "platform": platform,
                }
            )

        except Exception as e:
            self.logger.error(f"Failed to lock screen: {e}")
            return ToolOutput(success=False, data={}, error=str(e))

    def _lock(self, platform: str) -> None:
        """Execute the OS-specific lock command."""

        if platform == "win32":
            # Windows — locks immediately
            import ctypes
            ctypes.windll.user32.LockWorkStation()

        elif platform == "darwin":
            # macOS — two methods, try both
            try:
                subprocess.run(
                    ["pmset", "displaysleepnow"],
                    check=True, timeout=5
                )
            except Exception:
                # fallback — triggers screensaver which respects lock setting
                subprocess.run(
                    [
                        "osascript", "-e",
                        'tell application "System Events" to keystroke "q" '
                        'using {command down, control down}'
                    ],
                    check=True, timeout=5
                )

        elif platform.startswith("linux"):
            # Linux — try common lock tools in order
            lock_commands = [
                ["loginctl", "lock-session"],     # systemd (most common)
                ["xdg-screensaver", "lock"],       # generic X11
                ["gnome-screensaver-command", "-l"],  # GNOME
                ["xscreensaver-command", "-lock"],    # xscreensaver
                ["i3lock"],                           # i3wm
                ["slock"],                            # suckless
            ]

            for cmd in lock_commands:
                try:
                    subprocess.run(cmd, check=True, timeout=5)
                    return  # success — stop trying
                except (FileNotFoundError, subprocess.CalledProcessError):
                    continue

            raise RuntimeError(
                "No lock tool found. Install one of: "
                "loginctl, xdg-screensaver, gnome-screensaver, i3lock"
            )

        else:
            raise RuntimeError(f"Unsupported platform: {platform}")


__all__ = ["LockScreenTool"]