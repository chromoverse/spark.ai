"""
Brightness control tools for adjusting screen brightness.

Default increment/decrement: 1 unit
"""

import sys
import subprocess
import logging
from typing import Dict, Any
from datetime import datetime

from ..base import BaseTool, ToolOutput


class BrightnessStatusTool(BaseTool):
    """Get current screen brightness level."""

    def get_tool_name(self) -> str:
        return "brightness_status"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Get current brightness level."""
        try:
            brightness = self._get_brightness()
            
            return ToolOutput(
                success=True,
                data={
                    "brightness": brightness,
                    "min_brightness": 0,
                    "max_brightness": 100,
                    "timestamp": datetime.now().isoformat(),
                }
            )
        except Exception as e:
            self.logger.error(f"Failed to get brightness: {e}")
            return ToolOutput(success=False, data={}, error=str(e))

    def _get_brightness(self) -> int:
        """Get current brightness level based on OS."""
        if sys.platform == "win32":
            return self._get_brightness_windows()
        elif sys.platform == "darwin":
            return self._get_brightness_macos()
        else:
            return self._get_brightness_linux()

    def _get_brightness_windows(self) -> int:
        """Get brightness on Windows using WMI or PowerShell."""
        try:
            # Try using PowerShell with WMI
            cmd = (
                "Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightness | "
                "Select-Object -ExpandProperty CurrentBrightness"
            )
            result = subprocess.run(
                ["powershell", "-Command", cmd],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                return int(result.stdout.strip())
        except Exception as e:
            self.logger.warning(f"WMI brightness query failed: {e}")
        
        # Fallback: assume default brightness
        return 50

    def _get_brightness_macos(self) -> int:
        """Get brightness on macOS."""
        try:
            # Use brightness command if available
            result = subprocess.run(
                ["brightness", "-l"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                # Parse output for brightness level
                for line in result.stdout.split("\n"):
                    if "brightness" in line.lower():
                        # Extract percentage
                        parts = line.split()
                        for part in parts:
                            if "%" in part:
                                return int(part.replace("%", ""))
        except FileNotFoundError:
            self.logger.warning("brightness command not found on macOS")
        except Exception as e:
            self.logger.warning(f"macOS brightness query failed: {e}")
        
        return 50

    def _get_brightness_linux(self) -> int:
        """Get brightness on Linux using xbacklight or D-Bus."""
        try:
            # Try xbacklight
            result = subprocess.run(
                ["xbacklight", "-get"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                return int(float(result.stdout.strip()))
        except FileNotFoundError:
            self.logger.warning("xbacklight not found on Linux")
        except Exception as e:
            self.logger.warning(f"Linux brightness query failed: {e}")
        
        return 50


class BrightnessIncreaseTool(BaseTool):
    """Increase screen brightness by specified amount (default +10)."""

    def get_tool_name(self) -> str:
        return "brightness_increase"

    def __init__(self):
        super().__init__()
        self.status_tool = BrightnessStatusTool()

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Increase brightness by the specified amount."""
        amount = self.get_input(inputs, "amount", 10)  # Default +10
        
        try:
            # Get current brightness
            current = self.status_tool._get_brightness()
            new_brightness = min(100, current + amount)  # Cap at 100
            
            # Set new brightness
            self._set_brightness(new_brightness)
            
            return ToolOutput(
                success=True,
                data={
                    "previous_brightness": current,
                    "new_brightness": new_brightness,
                    "amount_changed": new_brightness - current,
                    "timestamp": datetime.now().isoformat(),
                }
            )
        except Exception as e:
            self.logger.error(f"Failed to increase brightness: {e}")
            return ToolOutput(success=False, data={}, error=str(e))

    def _set_brightness(self, level: int) -> None:
        """Set brightness level based on OS."""
        if sys.platform == "win32":
            self._set_brightness_windows(level)
        elif sys.platform == "darwin":
            self._set_brightness_macos(level)
        else:
            self._set_brightness_linux(level)

    def _set_brightness_windows(self, level: int) -> None:
        """Set brightness on Windows using WMI."""
        try:
            # PowerShell command to set brightness
            cmd = f"(Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1, {level})"
            subprocess.run(
                ["powershell", "-Command", cmd],
                capture_output=True,
                timeout=5
            )
        except Exception as e:
            self.logger.error(f"Failed to set Windows brightness: {e}")
            raise

    def _set_brightness_macos(self, level: int) -> None:
        """Set brightness on macOS."""
        try:
            # Use brightness command if available
            subprocess.run(
                ["brightness", str(level / 100)],  # brightness expects 0-1
                capture_output=True,
                timeout=5
            )
        except FileNotFoundError:
            # Fallback to AppleScript
            try:
                applescript = f'tell application "System Events" to key code {"144" if level < 50 else "145"}'
                subprocess.run(["osascript", "-e", applescript], timeout=5)
            except Exception as e:
                self.logger.error(f"Failed to set macOS brightness: {e}")
                raise
        except Exception as e:
            self.logger.error(f"Failed to set macOS brightness: {e}")
            raise

    def _set_brightness_linux(self, level: int) -> None:
        """Set brightness on Linux using xbacklight."""
        try:
            subprocess.run(
                ["xbacklight", "-set", str(level)],
                capture_output=True,
                timeout=5
            )
        except FileNotFoundError:
            self.logger.error("xbacklight not found on Linux")
            raise
        except Exception as e:
            self.logger.error(f"Failed to set Linux brightness: {e}")
            raise


class BrightnessDecreaseTool(BaseTool):
    """Decrease screen brightness by specified amount (default -10)."""

    def get_tool_name(self) -> str:
        return "brightness_decrease"

    def __init__(self):
        super().__init__()
        self.status_tool = BrightnessStatusTool()

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Decrease brightness by the specified amount."""
        amount = self.get_input(inputs, "amount", 10)  # Default -10
        
        try:
            # Get current brightness
            current = self.status_tool._get_brightness()
            new_brightness = max(0, current - amount)  # Floor at 0
            
            # Set new brightness
            self._set_brightness(new_brightness)
            
            return ToolOutput(
                success=True,
                data={
                    "previous_brightness": current,
                    "new_brightness": new_brightness,
                    "amount_changed": current - new_brightness,
                    "timestamp": datetime.now().isoformat(),
                }
            )
        except Exception as e:
            self.logger.error(f"Failed to decrease brightness: {e}")
            return ToolOutput(success=False, data={}, error=str(e))

    def _set_brightness(self, level: int) -> None:
        """Set brightness level based on OS."""
        if sys.platform == "win32":
            self._set_brightness_windows(level)
        elif sys.platform == "darwin":
            self._set_brightness_macos(level)
        else:
            self._set_brightness_linux(level)

    def _set_brightness_windows(self, level: int) -> None:
        """Set brightness on Windows using WMI."""
        try:
            cmd = f"(Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1, {level})"
            subprocess.run(
                ["powershell", "-Command", cmd],
                capture_output=True,
                timeout=5
            )
        except Exception as e:
            self.logger.error(f"Failed to set Windows brightness: {e}")
            raise

    def _set_brightness_macos(self, level: int) -> None:
        """Set brightness on macOS."""
        try:
            subprocess.run(
                ["brightness", str(level / 100)],
                capture_output=True,
                timeout=5
            )
        except FileNotFoundError:
            try:
                applescript = f'tell application "System Events" to key code "144"'
                subprocess.run(["osascript", "-e", applescript], timeout=5)
            except Exception as e:
                self.logger.error(f"Failed to set macOS brightness: {e}")
                raise
        except Exception as e:
            self.logger.error(f"Failed to set macOS brightness: {e}")
            raise

    def _set_brightness_linux(self, level: int) -> None:
        """Set brightness on Linux using xbacklight."""
        try:
            subprocess.run(
                ["xbacklight", "-set", str(level)],
                capture_output=True,
                timeout=5
            )
        except FileNotFoundError:
            self.logger.error("xbacklight not found on Linux")
            raise
        except Exception as e:
            self.logger.error(f"Failed to set Linux brightness: {e}")
            raise


# Export all tools for registration
__all__ = ["BrightnessStatusTool", "BrightnessIncreaseTool", "BrightnessDecreaseTool"]