"""
Sound/Volume control tools for adjusting system audio.

Default increment/decrement: 30 units (out of 100)
"""

import asyncio
import sys
import subprocess
import logging
from typing import Dict, Any, Tuple
from datetime import datetime

from app.plugins.tools.tool_base import BaseTool, ToolOutput


class SoundStatusTool(BaseTool):
    """Get current system volume level and mute status."""

    TOOL_DESCRIPTION = "Get current system volume level and mute status"
    EXECUTION_TARGET = "client"
    PARAMS_SCHEMA: Dict[str, Any] = {}
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {
            "volume": {"type": "integer"},
            "is_muted": {"type": "boolean"},
            "min_volume": {"type": "integer"},
            "max_volume": {"type": "integer"},
            "timestamp": {"type": "string"},
        },
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "sound status"}]
    SEMANTIC_TAGS = ["system", "sound", "status"]
    TOOL_CATEGORY = "system_control"

    def get_tool_name(self) -> str:
        return "sound_status"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Get current volume level and mute status."""
        try:
            volume, is_muted = await asyncio.to_thread(self._get_volume_status)

            return ToolOutput(
                success=True,
                data={
                    "volume": volume,
                    "is_muted": is_muted,
                    "min_volume": 0,
                    "max_volume": 100,
                    "timestamp": datetime.now().isoformat(),
                }
            )
        except Exception as e:
            self.logger.error(f"Failed to get sound status: {e}")
            return ToolOutput(success=False, data={}, error=str(e))

    def _get_volume_status(self) -> Tuple[int, bool]:
        """Get current volume level and mute status based on OS."""
        if sys.platform == "win32":
            return self._get_volume_windows()
        elif sys.platform == "darwin":
            return self._get_volume_macos()
        else:
            return self._get_volume_linux()

    def _get_volume_windows(self) -> Tuple[int, bool]:
        """Get volume on Windows using pycaw library."""
        try:
            from pycaw.pycaw import AudioUtilities

            devices = AudioUtilities.GetSpeakers()
            volume = devices.EndpointVolume #type:ignore

            current_volume = volume.GetMasterVolumeLevelScalar()  # type: ignore
            volume_percent = round(current_volume * 100)

            is_muted = bool(volume.GetMute())  # type: ignore

            return (volume_percent, is_muted)

        except Exception as e:
            self.logger.error(f"Failed to get Windows volume: {e}")
            return (50, False)

    def _get_volume_macos(self) -> Tuple[int, bool]:
        """Get volume on macOS using osascript."""
        try:
            result = subprocess.run(
                ["osascript", "-e", "output volume of (get volume settings)"],
                capture_output=True,
                text=True,
                timeout=5
            )
            volume = int(result.stdout.strip()) if result.returncode == 0 else 50

            result_mute = subprocess.run(
                ["osascript", "-e", "output muted of (get volume settings)"],
                capture_output=True,
                text=True,
                timeout=5
            )
            is_muted = result_mute.stdout.strip().lower() == "true"

            return (volume, is_muted)
        except Exception as e:
            self.logger.warning(f"macOS volume query failed: {e}")
            return (50, False)

    def _get_volume_linux(self) -> Tuple[int, bool]:
        """Get volume on Linux using pactl or amixer."""
        try:
            result = subprocess.run(
                ["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                import re
                match = re.search(r'(\d+)%', result.stdout)
                if match:
                    volume = int(match.group(1))

                    result_mute = subprocess.run(
                        ["pactl", "get-sink-mute", "@DEFAULT_SINK@"],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    is_muted = "yes" in result_mute.stdout.lower()
                    return (volume, is_muted)
        except FileNotFoundError:
            pass
        except Exception as e:
            self.logger.warning(f"Linux pulseaudio volume query failed: {e}")

        try:
            result = subprocess.run(
                ["amixer", "get", "Master"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                import re
                match = re.search(r'\[(\d+)%\]', result.stdout)
                volume = int(match.group(1)) if match else 50
                is_muted = "[off]" in result.stdout
                return (volume, is_muted)
        except FileNotFoundError:
            self.logger.warning("Neither pactl nor amixer found on Linux")
        except Exception as e:
            self.logger.warning(f"Linux ALSA volume query failed: {e}")

        return (50, False)


class SoundIncreaseTool(BaseTool):
    """Increase system volume by specified amount (default +30)."""

    TOOL_DESCRIPTION = "Increase system volume by specified amount (0-100 scale). Use amount=10 for a small bump, amount=30 for moderate, amount=50+ for large increase."
    EXECUTION_TARGET = "client"
    PARAMS_SCHEMA: Dict[str, Any] = {
        "amount": {"type": "integer", "required": False, "default": 10, "description": "Amount to increase volume by on 0-100 scale (default 10). Use 100 to go to max volume."},
    }
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {
            "previous_volume": {"type": "integer"},
            "new_volume": {"type": "integer"},
            "amount_changed": {"type": "integer"},
            "timestamp": {"type": "string"},
        },
        "error": {"type": "string"},
    }
    EXAMPLES = [
        {"user_utterance": "increase volume", "inputs": {"amount": 10}},
        {"user_utterance": "turn it up", "inputs": {"amount": 20}},
        {"user_utterance": "volume to maximum", "inputs": {"amount": 100}},
        {"user_utterance": "louder please", "inputs": {"amount": 15}},
    ]
    SEMANTIC_TAGS = ["system", "sound", "increase"]
    TOOL_CATEGORY = "system_control"

    def get_tool_name(self) -> str:
        return "sound_increase"

    def __init__(self):
        super().__init__()
        self.status_tool = SoundStatusTool()

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Increase volume by the specified amount."""
        amount = self.get_input(inputs, "amount", 10)

        try:
            current, _ = await asyncio.to_thread(self.status_tool._get_volume_status)
            new_volume = min(100, current + amount)

            await asyncio.to_thread(self._set_volume, new_volume)

            return ToolOutput(
                success=True,
                data={
                    "previous_volume": current,
                    "new_volume": new_volume,
                    "amount_changed": new_volume - current,
                    "timestamp": datetime.now().isoformat(),
                }
            )
        except Exception as e:
            self.logger.error(f"Failed to increase volume: {e}")
            return ToolOutput(success=False, data={}, error=str(e))

    def _set_volume(self, level: int) -> None:
        """Set volume level based on OS."""
        if sys.platform == "win32":
            self._set_volume_windows(level)
        elif sys.platform == "darwin":
            self._set_volume_macos(level)
        else:
            self._set_volume_linux(level)

    def _set_volume_windows(self, level: int) -> None:
        """Set volume on Windows using pycaw library."""
        try:
            from pycaw.pycaw import AudioUtilities

            devices = AudioUtilities.GetSpeakers()
            volume = devices.EndpointVolume  #type:ignore

            volume.SetMasterVolumeLevelScalar(level / 100.0, None)  # type: ignore

        except Exception as e:
            self.logger.error(f"Failed to set Windows volume: {e}")
            raise

    def _set_volume_macos(self, level: int) -> None:
        """Set volume on macOS using osascript."""
        try:
            subprocess.run(
                ["osascript", "-e", f"set volume output volume {level}"],
                capture_output=True,
                timeout=5
            )
        except Exception as e:
            self.logger.error(f"Failed to set macOS volume: {e}")
            raise

    def _set_volume_linux(self, level: int) -> None:
        """Set volume on Linux using pactl or amixer."""
        try:
            subprocess.run(
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"],
                capture_output=True,
                timeout=5
            )
            return
        except FileNotFoundError:
            pass
        except Exception as e:
            self.logger.warning(f"pactl volume set failed: {e}")

        try:
            subprocess.run(
                ["amixer", "set", "Master", f"{level}%"],
                capture_output=True,
                timeout=5
            )
        except FileNotFoundError:
            self.logger.error("Neither pactl nor amixer found on Linux")
            raise
        except Exception as e:
            self.logger.error(f"Failed to set Linux volume: {e}")
            raise


class SoundDecreaseTool(BaseTool):
    """Decrease system volume by specified amount (default -30)."""

    TOOL_DESCRIPTION = "Decrease system volume by specified amount (0-100 scale). Use amount=10 for a small decrease, amount=30 for moderate, amount=50+ for large decrease."
    EXECUTION_TARGET = "client"
    PARAMS_SCHEMA: Dict[str, Any] = {
        "amount": {"type": "integer", "required": False, "default": 10, "description": "Amount to decrease volume by on 0-100 scale (default 10). Use 100 to mute completely."},
    }
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {
            "previous_volume": {"type": "integer"},
            "new_volume": {"type": "integer"},
            "amount_changed": {"type": "integer"},
            "timestamp": {"type": "string"},
        },
        "error": {"type": "string"},
    }
    EXAMPLES = [
        {"user_utterance": "decrease volume", "inputs": {"amount": 10}},
        {"user_utterance": "turn it down", "inputs": {"amount": 20}},
        {"user_utterance": "lower the volume a lot", "inputs": {"amount": 50}},
        {"user_utterance": "make it quieter", "inputs": {"amount": 15}},
        {"user_utterance": "volume to minimum", "inputs": {"amount": 100}},
    ]
    SEMANTIC_TAGS = ["system", "sound", "decrease"]
    TOOL_CATEGORY = "system_control"

    def get_tool_name(self) -> str:
        return "sound_decrease"

    def __init__(self):
        super().__init__()
        self.status_tool = SoundStatusTool()

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Decrease volume by the specified amount."""
        amount = self.get_input(inputs, "amount", 10)

        try:
            current, _ = await asyncio.to_thread(self.status_tool._get_volume_status)
            new_volume = max(0, current - amount)

            await asyncio.to_thread(self._set_volume, new_volume)

            return ToolOutput(
                success=True,
                data={
                    "previous_volume": current,
                    "new_volume": new_volume,
                    "amount_changed": current - new_volume,
                    "timestamp": datetime.now().isoformat(),
                }
            )
        except Exception as e:
            self.logger.error(f"Failed to decrease volume: {e}")
            return ToolOutput(success=False, data={}, error=str(e))

    def _set_volume(self, level: int) -> None:
        """Set volume level based on OS."""
        if sys.platform == "win32":
            self._set_volume_windows(level)
        elif sys.platform == "darwin":
            self._set_volume_macos(level)
        else:
            self._set_volume_linux(level)

    def _set_volume_windows(self, level: int) -> None:
        """Set volume on Windows using pycaw library."""
        try:
            from pycaw.pycaw import AudioUtilities

            devices = AudioUtilities.GetSpeakers()
            volume = devices.EndpointVolume #type:ignore

            volume.SetMasterVolumeLevelScalar(level / 100.0, None)  # type: ignore

        except Exception as e:
            self.logger.error(f"Failed to set Windows volume: {e}")
            raise

    def _set_volume_macos(self, level: int) -> None:
        """Set volume on macOS using osascript."""
        try:
            subprocess.run(
                ["osascript", "-e", f"set volume output volume {level}"],
                capture_output=True,
                timeout=5
            )
        except Exception as e:
            self.logger.error(f"Failed to set macOS volume: {e}")
            raise

    def _set_volume_linux(self, level: int) -> None:
        """Set volume on Linux using pactl or amixer."""
        try:
            subprocess.run(
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"],
                capture_output=True,
                timeout=5
            )
            return
        except FileNotFoundError:
            pass
        except Exception as e:
            self.logger.warning(f"pactl volume set failed: {e}")

        try:
            subprocess.run(
                ["amixer", "set", "Master", f"{level}%"],
                capture_output=True,
                timeout=5
            )
        except FileNotFoundError:
            self.logger.error("Neither pactl nor amixer found on Linux")
            raise
        except Exception as e:
            self.logger.error(f"Failed to set Linux volume: {e}")
            raise


__all__ = ["SoundStatusTool", "SoundIncreaseTool", "SoundDecreaseTool"]
