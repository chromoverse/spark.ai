"""
Battery status and power management tools.
"""

import sys
import subprocess
import logging
from typing import Dict, Any
from datetime import datetime

from ..base import BaseTool, ToolOutput


class BatteryStatusTool(BaseTool):
    """Get battery status and power information."""

    def get_tool_name(self) -> str:
        return "battery_status"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Get battery status including percentage, charging state, and health."""
        try:
            battery_info = self._get_battery_info()
            
            return ToolOutput(
                success=True,
                data={
                    "percent": battery_info.get("percent", 0),
                    "is_charging": battery_info.get("is_charging", False),
                    "time_remaining": battery_info.get("time_remaining", "N/A"),
                    "health": battery_info.get("health", "Unknown"),
                    "timestamp": datetime.now().isoformat(),
                }
            )
        except Exception as e:
            self.logger.error(f"Failed to get battery status: {e}")
            return ToolOutput(success=False, data={}, error=str(e))

    def _get_battery_info(self) -> Dict[str, Any]:
        """Get battery info based on OS."""
        if sys.platform == "win32":
            return self._get_battery_windows()
        elif sys.platform == "darwin":
            return self._get_battery_macos()
        else:
            return self._get_battery_linux()

    def _get_battery_windows(self) -> Dict[str, Any]:
        """Get battery info on Windows using WMI."""
        try:
            # Use PowerShell to get battery info
            ps_script = '''
Add-Type -AssemblyName System.Windows.Forms
$powerStatus = [System.Windows.Forms.SystemInformation]::PowerStatus
Write-Output "Percent:$($powerStatus.BatteryLifePercent * 100)"
Write-Output "Charging:$($powerStatus.PowerLineStatus -eq 'Online')"
Write-Output "Remaining:$($powerStatus.BatteryLifeRemaining)"
'''
            result = subprocess.run(
                ["powershell", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                info = {}
                for line in result.stdout.strip().split('\n'):
                    if ':' in line:
                        key, value = line.split(':', 1)
                        if key == "Percent":
                            info["percent"] = int(float(value))
                        elif key == "Charging":
                            info["is_charging"] = value.lower() == "true"
                        elif key == "Remaining":
                            try:
                                secs = int(value)
                                if secs > 0:
                                    hours = secs // 3600
                                    mins = (secs % 3600) // 60
                                    info["time_remaining"] = f"{hours}h {mins}m"
                                else:
                                    info["time_remaining"] = "Calculating..."
                            except:
                                info["time_remaining"] = "N/A"
                
                # Get battery health via WMI
                health_result = subprocess.run(
                    ["powershell", "-Command", 
                     "Get-WmiObject -Class Win32_Battery | Select-Object -ExpandProperty Status"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if health_result.returncode == 0 and health_result.stdout.strip():
                    info["health"] = health_result.stdout.strip()
                else:
                    info["health"] = "OK"
                
                return info
        except Exception as e:
            self.logger.warning(f"Windows battery query failed: {e}")
        
        return {"percent": 0, "is_charging": False, "time_remaining": "N/A", "health": "Unknown"}

    def _get_battery_macos(self) -> Dict[str, Any]:
        """Get battery info on macOS using pmset."""
        try:
            result = subprocess.run(
                ["pmset", "-g", "batt"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                info = {}
                output = result.stdout
                
                # Parse percentage
                import re
                percent_match = re.search(r'(\d+)%', output)
                if percent_match:
                    info["percent"] = int(percent_match.group(1))
                
                # Parse charging status
                info["is_charging"] = "charging" in output.lower() or "AC attached" in output
                
                # Parse time remaining
                time_match = re.search(r'(\d+:\d+) remaining', output)
                if time_match:
                    info["time_remaining"] = time_match.group(1)
                else:
                    info["time_remaining"] = "Calculating..."
                
                # Health check via system_profiler
                health_result = subprocess.run(
                    ["system_profiler", "SPPowerDataType"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if health_result.returncode == 0:
                    if "Condition: Normal" in health_result.stdout:
                        info["health"] = "Good"
                    elif "Condition: Service" in health_result.stdout:
                        info["health"] = "Service Required"
                    else:
                        info["health"] = "OK"
                else:
                    info["health"] = "OK"
                
                return info
        except Exception as e:
            self.logger.warning(f"macOS battery query failed: {e}")
        
        return {"percent": 0, "is_charging": False, "time_remaining": "N/A", "health": "Unknown"}

    def _get_battery_linux(self) -> Dict[str, Any]:
        """Get battery info on Linux using UPower or sysfs."""
        try:
            # Try UPower first
            result = subprocess.run(
                ["upower", "-i", "/org/freedesktop/UPower/devices/battery_BAT0"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                info = {}
                output = result.stdout
                
                import re
                # Parse percentage
                percent_match = re.search(r'percentage:\s*(\d+)%', output)
                if percent_match:
                    info["percent"] = int(percent_match.group(1))
                
                # Parse state
                state_match = re.search(r'state:\s*(\w+)', output)
                if state_match:
                    state = state_match.group(1).lower()
                    info["is_charging"] = state in ("charging", "fully-charged")
                
                # Parse time to empty/full
                time_match = re.search(r'time to empty:\s*([\d.]+)\s*hours', output)
                if time_match:
                    hours = float(time_match.group(1))
                    h = int(hours)
                    m = int((hours - h) * 60)
                    info["time_remaining"] = f"{h}h {m}m"
                else:
                    info["time_remaining"] = "N/A"
                
                # Health
                health_match = re.search(r'capacity:\s*(\d+)%', output)
                if health_match:
                    cap = int(health_match.group(1))
                    if cap > 80:
                        info["health"] = "Good"
                    elif cap > 60:
                        info["health"] = "Fair"
                    else:
                        info["health"] = "Poor"
                else:
                    info["health"] = "OK"
                
                return info
        except FileNotFoundError:
            pass
        except Exception as e:
            self.logger.warning(f"UPower battery query failed: {e}")
        
        # Fallback to sysfs
        try:
            info = {}
            
            # Read capacity
            with open("/sys/class/power_supply/BAT0/capacity", "r") as f:
                info["percent"] = int(f.read().strip())
            
            # Read status
            with open("/sys/class/power_supply/BAT0/status", "r") as f:
                status = f.read().strip().lower()
                info["is_charging"] = status in ("charging", "full")
            
            info["time_remaining"] = "N/A"
            info["health"] = "OK"
            
            return info
        except Exception as e:
            self.logger.warning(f"sysfs battery query failed: {e}")
        
        return {"percent": 0, "is_charging": False, "time_remaining": "N/A", "health": "Unknown"}


# Export all tools for registration
__all__ = ["BatteryStatusTool"]