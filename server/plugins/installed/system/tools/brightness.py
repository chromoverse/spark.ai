"""
Brightness control tools for adjusting screen brightness.

Default increment/decrement: 10 units (out of 100)

Backends (tried in order)
─────────────────────────
1. screen-brightness-control (sbc)  — cross-platform, fast (~20ms),
   handles built-in panels via OS APIs and external monitors via DDC/CI.
2. OS-specific fallbacks:
     • Windows : PowerShell + WMI (laptop panel only, ~2s)
     • macOS   : `brightness` CLI (brew install brightness)
     • Linux   : xbacklight, then brightnessctl
"""

import asyncio
import sys
import subprocess
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from app.plugins.tools.tool_base import BaseTool, ToolOutput

logger = logging.getLogger(__name__)


# ── sbc helpers (module-level, shared by status/increase/decrease) ─────────────

def _sbc_module():
    """Lazy import sbc; returns the module or None if unavailable."""
    try:
        import screen_brightness_control as sbc  # type: ignore
        return sbc
    except Exception as e:
        logger.debug("screen-brightness-control unavailable: %s", e)
        return None


def _sbc_get_per_display() -> Optional[List[int]]:
    """Return per-display brightness percentages, or None if sbc isn't usable."""
    sbc = _sbc_module()
    if sbc is None:
        return None
    try:
        levels = sbc.get_brightness()
    except Exception as e:
        logger.warning("sbc.get_brightness failed: %s", e)
        return None
    # sbc returns list[int] (one per monitor); be defensive about scalar return.
    if isinstance(levels, int):
        return [int(levels)]
    if isinstance(levels, (list, tuple)) and levels:
        try:
            return [int(x) for x in levels]
        except (TypeError, ValueError):
            return None
    return None


def _sbc_set_all(level: int) -> bool:
    """Set every connected display to `level`. Returns True on success."""
    sbc = _sbc_module()
    if sbc is None:
        return False
    try:
        sbc.set_brightness(level)
        return True
    except Exception as e:
        logger.warning("sbc.set_brightness failed: %s", e)
        return False


def _sbc_set_relative(delta: int) -> Optional[List[int]]:
    """Adjust every display by `delta`, preserving per-monitor offsets.

    Returns the new per-display levels on success, or None if sbc unusable.
    """
    sbc = _sbc_module()
    if sbc is None:
        return None
    try:
        per = _sbc_get_per_display()
        if per is None:
            return None
        # Use list_monitors for stable index → display mapping.
        try:
            mons = sbc.list_monitors()
        except Exception:
            mons = list(range(len(per)))
        new_levels: List[int] = []
        for idx, current in enumerate(per):
            target = max(0, min(100, current + delta))
            try:
                sbc.set_brightness(target, display=idx)
            except Exception:
                # If indexed-set fails (driver oddity), try by monitor name.
                try:
                    sbc.set_brightness(target, display=mons[idx])
                except Exception as e:
                    logger.warning("sbc set_brightness display=%s failed: %s", idx, e)
                    return None
            new_levels.append(target)
        return new_levels
    except Exception as e:
        logger.warning("sbc relative set failed: %s", e)
        return None


class BrightnessStatusTool(BaseTool):
    """Get current screen brightness level.

    Inputs:
    - (None)

    Outputs:
    - brightness (integer)
    - min_brightness (integer)
    - max_brightness (integer)
    - timestamp (string)
    """

    TOOL_DESCRIPTION = "Get current screen brightness level"
    EXECUTION_TARGET = "client"
    PARAMS_SCHEMA: Dict[str, Any] = {}
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {
            "brightness": {"type": "integer"},
            "min_brightness": {"type": "integer"},
            "max_brightness": {"type": "integer"},
            "timestamp": {"type": "string"},
        },
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "brightness status"}]
    SEMANTIC_TAGS = ["system", "brightness", "status"]
    TOOL_CATEGORY = "system_control"

    def get_tool_name(self) -> str:
        return "brightness_status"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Get current brightness level."""
        try:
            per = await asyncio.to_thread(_sbc_get_per_display)
            if per:
                brightness = round(sum(per) / len(per))
                # list_monitors is best-effort metadata, not a hard requirement
                try:
                    sbc = _sbc_module()
                    monitors = sbc.list_monitors() if sbc else []
                except Exception:
                    monitors = []
                displays = [
                    {"index": i, "name": monitors[i] if i < len(monitors) else f"display_{i}", "brightness": v}
                    for i, v in enumerate(per)
                ]
            else:
                brightness = await asyncio.to_thread(self._get_brightness)
                displays = [{"index": 0, "name": "primary", "brightness": brightness}]

            return ToolOutput(
                success=True,
                data={
                    "brightness": brightness,
                    "displays": displays,
                    "min_brightness": 0,
                    "max_brightness": 100,
                    "timestamp": datetime.now().isoformat(),
                }
            )
        except Exception as e:
            self.logger.error(f"Failed to get brightness: {e}")
            return ToolOutput(success=False, data={}, error=str(e))

    def _get_brightness(self) -> int:
        """Get current brightness — sbc first, then OS-specific fallback.

        When multiple displays are connected, returns the average across
        all of them (rounded). The status tool also exposes the per-display
        list separately so the agent can inspect.
        """
        per = _sbc_get_per_display()
        if per:
            return round(sum(per) / len(per))
        if sys.platform == "win32":
            return self._get_brightness_windows()
        elif sys.platform == "darwin":
            return self._get_brightness_macos()
        else:
            return self._get_brightness_linux()

    def _get_brightness_windows(self) -> int:
        """Get brightness on Windows using WMI via PowerShell.

        Note: WmiMonitorBrightness only reports the integrated panel. External
        monitors (HDMI/DP/DDC-CI) are NOT visible through this API. If you need
        external-monitor support, install `screen-brightness-control` and switch
        the implementation.
        """
        try:
            cmd = (
                "Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightness | "
                "Select-Object -ExpandProperty CurrentBrightness"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception as e:
            raise RuntimeError(f"WMI brightness query crashed: {e}") from e

        if result.returncode != 0:
            raise RuntimeError(
                f"WMI brightness query failed (rc={result.returncode}): "
                f"{(result.stderr or '').strip()[:200]}"
            )
        out = (result.stdout or "").strip()
        if not out:
            raise RuntimeError(
                "WMI returned no brightness value — display does not expose "
                "WmiMonitorBrightness (likely an external monitor)."
            )
        try:
            return int(out.splitlines()[0].strip())
        except ValueError as e:
            raise RuntimeError(
                f"WMI returned non-integer brightness '{out[:60]}': {e}"
            ) from e

    def _get_brightness_macos(self) -> int:
        """Get brightness on macOS via the `brightness` CLI (brew install brightness)."""
        try:
            result = subprocess.run(
                ["brightness", "-l"],
                capture_output=True,
                text=True,
                timeout=5
            )
        except FileNotFoundError as e:
            raise RuntimeError(
                "macOS `brightness` CLI not found — install with `brew install brightness`."
            ) from e
        except Exception as e:
            raise RuntimeError(f"macOS brightness query crashed: {e}") from e

        if result.returncode != 0:
            raise RuntimeError(
                f"`brightness -l` failed (rc={result.returncode}): "
                f"{(result.stderr or '').strip()[:200]}"
            )

        for line in (result.stdout or "").split("\n"):
            if "brightness" in line.lower():
                # Format: "display 0: brightness 0.5" — value is 0.0–1.0
                for token in line.split():
                    try:
                        f = float(token)
                        if 0.0 <= f <= 1.0:
                            return round(f * 100)
                    except ValueError:
                        continue
                # Some builds emit "brightness 50%" — handle that too
                for token in line.split():
                    if "%" in token:
                        try:
                            return int(token.replace("%", "").strip())
                        except ValueError:
                            continue
        raise RuntimeError(
            f"Could not parse brightness from `brightness -l` output: "
            f"{(result.stdout or '')[:200]}"
        )

    def _get_brightness_linux(self) -> int:
        """Get brightness on Linux. Tries xbacklight, then brightnessctl."""
        # Try xbacklight first (X11 / DDC-CI)
        try:
            result = subprocess.run(
                ["xbacklight", "-get"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                return int(float(result.stdout.strip()))
        except FileNotFoundError:
            pass  # try next backend
        except Exception as e:
            raise RuntimeError(f"xbacklight crashed: {e}") from e

        # Fallback: brightnessctl (works on Wayland too)
        try:
            cur = subprocess.run(
                ["brightnessctl", "g"],
                capture_output=True, text=True, timeout=5,
            )
            mx = subprocess.run(
                ["brightnessctl", "m"],
                capture_output=True, text=True, timeout=5,
            )
            if cur.returncode == 0 and mx.returncode == 0:
                cur_v = int(cur.stdout.strip())
                max_v = int(mx.stdout.strip())
                if max_v > 0:
                    return round(cur_v * 100 / max_v)
        except FileNotFoundError:
            pass

        raise RuntimeError(
            "No working brightness backend found on Linux. "
            "Install one of: xbacklight, brightnessctl"
        )


class BrightnessIncreaseTool(BaseTool):
    """Increase screen brightness by specified amount (default +10).

    Inputs:
    - amount (integer, optional): Amount to increase brightness by (default 1)

    Outputs:
    - previous_brightness (integer)
    - new_brightness (integer)
    - amount_changed (integer)
    - timestamp (string)
    """

    TOOL_DESCRIPTION = "Increase screen brightness by specified amount (0-100 scale). Use amount=10 for a small bump, amount=30 for moderate, amount=50+ for large increase. To set to max, use amount=100."
    EXECUTION_TARGET = "client"
    PARAMS_SCHEMA: Dict[str, Any] = {
        "amount": {"type": "integer", "required": False, "default": 10, "description": "Amount to increase brightness by on 0-100 scale (default 10). Use 100 to go to maximum."},
    }
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {
            "previous_brightness": {"type": "integer"},
            "new_brightness": {"type": "integer"},
            "amount_changed": {"type": "integer"},
            "timestamp": {"type": "string"},
        },
        "error": {"type": "string"},
    }
    EXAMPLES = [
        {"user_utterance": "increase brightness", "inputs": {"amount": 10}},
        {"user_utterance": "make it brighter", "inputs": {"amount": 20}},
        {"user_utterance": "brightness to maximum", "inputs": {"amount": 100}},
        {"user_utterance": "increase brightness a little", "inputs": {"amount": 10}},
        {"user_utterance": "increase brightness a lot", "inputs": {"amount": 50}},
    ]
    SEMANTIC_TAGS = ["system", "brightness", "increase"]
    TOOL_CATEGORY = "system_control"

    def get_tool_name(self) -> str:
        return "brightness_increase"

    def __init__(self):
        super().__init__()
        self.status_tool = BrightnessStatusTool()

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Increase brightness by the specified amount.

        When sbc is available, every connected display is shifted by `amount`
        (preserving per-monitor offsets). Falls back to OS-specific code that
        targets the integrated panel only.
        """
        amount = self.get_input(inputs, "amount", 10)  # Default +10

        try:
            # ── sbc fast path: per-display relative adjust ────────────────────
            before_per = await asyncio.to_thread(_sbc_get_per_display)
            if before_per is not None:
                after_per = await asyncio.to_thread(_sbc_set_relative, int(amount))
                if after_per is not None:
                    prev_avg = round(sum(before_per) / len(before_per))
                    new_avg = round(sum(after_per) / len(after_per))
                    return ToolOutput(
                        success=True,
                        data={
                            "previous_brightness": prev_avg,
                            "new_brightness": new_avg,
                            "amount_changed": new_avg - prev_avg,
                            "displays_changed": len(after_per),
                            "displays_before": before_per,
                            "displays_after": after_per,
                            "timestamp": datetime.now().isoformat(),
                        }
                    )

            # ── OS-specific fallback (single integrated panel) ────────────────
            current = self.status_tool._get_brightness()
            new_brightness = min(100, current + amount)
            await asyncio.to_thread(self._set_brightness, new_brightness)

            return ToolOutput(
                success=True,
                data={
                    "previous_brightness": current,
                    "new_brightness": new_brightness,
                    "amount_changed": new_brightness - current,
                    "displays_changed": 1,
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
                ["brightness", str(level / 100)],  # brightness expects 0-1
                capture_output=True,
                timeout=5
            )
        except FileNotFoundError:
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
    """Decrease screen brightness by specified amount (default -10).

    Inputs:
    - amount (integer, optional): Amount to decrease brightness by (default 1)

    Outputs:
    - previous_brightness (integer)
    - new_brightness (integer)
    - amount_changed (integer)
    - timestamp (string)
    """

    TOOL_DESCRIPTION = "Decrease screen brightness by specified amount (0-100 scale). Use amount=10 for a small decrease, amount=30 for moderate, amount=50+ for large decrease. To set to minimum, use amount=100."
    EXECUTION_TARGET = "client"
    PARAMS_SCHEMA: Dict[str, Any] = {
        "amount": {"type": "integer", "required": False, "default": 10, "description": "Amount to decrease brightness by on 0-100 scale (default 10). Use 100 to go to minimum."},
    }
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {
            "previous_brightness": {"type": "integer"},
            "new_brightness": {"type": "integer"},
            "amount_changed": {"type": "integer"},
            "timestamp": {"type": "string"},
        },
        "error": {"type": "string"},
    }
    EXAMPLES = [
        {"user_utterance": "decrease brightness", "inputs": {"amount": 10}},
        {"user_utterance": "make it darker", "inputs": {"amount": 20}},
        {"user_utterance": "brightness to minimum", "inputs": {"amount": 100}},
        {"user_utterance": "lower brightness a little", "inputs": {"amount": 10}},
        {"user_utterance": "lower brightness a lot", "inputs": {"amount": 50}},
        {"user_utterance": "dim the screen", "inputs": {"amount": 30}},
    ]
    SEMANTIC_TAGS = ["system", "brightness", "decrease"]
    TOOL_CATEGORY = "system_control"

    def get_tool_name(self) -> str:
        return "brightness_decrease"

    def __init__(self):
        super().__init__()
        self.status_tool = BrightnessStatusTool()

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Decrease brightness by the specified amount.

        When sbc is available, every connected display is shifted by `-amount`
        (preserving per-monitor offsets). Falls back to OS-specific code that
        targets the integrated panel only.
        """
        amount = self.get_input(inputs, "amount", 10)  # Default -10

        try:
            # ── sbc fast path: per-display relative adjust ────────────────────
            before_per = await asyncio.to_thread(_sbc_get_per_display)
            if before_per is not None:
                after_per = await asyncio.to_thread(_sbc_set_relative, -int(amount))
                if after_per is not None:
                    prev_avg = round(sum(before_per) / len(before_per))
                    new_avg = round(sum(after_per) / len(after_per))
                    return ToolOutput(
                        success=True,
                        data={
                            "previous_brightness": prev_avg,
                            "new_brightness": new_avg,
                            "amount_changed": prev_avg - new_avg,
                            "displays_changed": len(after_per),
                            "displays_before": before_per,
                            "displays_after": after_per,
                            "timestamp": datetime.now().isoformat(),
                        }
                    )

            # ── OS-specific fallback (single integrated panel) ────────────────
            current = self.status_tool._get_brightness()
            new_brightness = max(0, current - amount)
            await asyncio.to_thread(self._set_brightness, new_brightness)

            return ToolOutput(
                success=True,
                data={
                    "previous_brightness": current,
                    "new_brightness": new_brightness,
                    "amount_changed": current - new_brightness,
                    "displays_changed": 1,
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
