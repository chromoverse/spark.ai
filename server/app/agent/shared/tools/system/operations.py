"""
System tools operations - Main entry point.

This module re-exports all system tools from their respective sub-modules:
- app.py: Application management tools (open, close, restart, minimize, maximize, focus)
- battery.py: Battery status tools
- brightness.py: Brightness control tools (status, increase, decrease)
- sound.py: Sound/volume control tools (status, increase, decrease)
- network.py: Network status tools
- clipboard.py: Clipboard operations (read, write)
- screenshot.py: Screenshot capture tools
"""

# Import all tools from sub-modules
from .app import (
    AppOpenTool,
    AppCloseTool,
    AppRestartTool,
    AppMinimizeTool,
    AppMaximizeTool,
    AppFocusTool,
)

from .battery import BatteryStatusTool

from .brightness import (
    BrightnessStatusTool,
    BrightnessIncreaseTool,
    BrightnessDecreaseTool,
)

from .sound import (
    SoundStatusTool,
    SoundIncreaseTool,
    SoundDecreaseTool,
)

from .network import NetworkStatusTool

from .clipboard import (
    ClipboardReadTool,
    ClipboardWriteTool,
)

from .screenshot import ScreenshotCaptureTool


# System info tool (kept here as it's simple)
import psutil
import logging
from typing import Dict, Any
from datetime import datetime

from ..base import BaseTool, ToolOutput


class SystemInfoTool(BaseTool):
    """Get CPU, RAM, Disk usage."""

    def get_tool_name(self) -> str:
        return "system_info"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Get system metrics."""
        metrics = self.get_input(inputs, "metrics", ["cpu", "ram", "disk"])
        
        try:
            data = {}
            
            if "cpu" in metrics:
                data["cpu_percent"] = psutil.cpu_percent(interval=0.5)
            
            if "ram" in metrics:
                ram = psutil.virtual_memory()
                data["ram_percent"] = ram.percent
                data["ram_used_gb"] = round(ram.used / (1024**3), 2)
                data["ram_total_gb"] = round(ram.total / (1024**3), 2)
            
            if "disk" in metrics:
                disk = psutil.disk_usage('/')
                data["disk_percent"] = disk.percent
                data["disk_used_gb"] = round(disk.used / (1024**3), 2)
                data["disk_total_gb"] = round(disk.total / (1024**3), 2)
            
            data["timestamp"] = datetime.now().isoformat()
            
            return ToolOutput(success=True, data=data)
            
        except Exception as e:
            self.logger.error(f"Failed to get system info: {e}")
            return ToolOutput(success=False, data={}, error=str(e))


# Notification tool (kept here as it's simple)
import sys
import subprocess


class NotificationPushTool(BaseTool):
    """Send native OS notifications."""

    def get_tool_name(self) -> str:
        return "notification_push"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Send a notification."""
        title = inputs.get("title", "Notification")
        message = inputs.get("message", "")
        urgency = self.get_input(inputs, "urgency", "normal")
        
        if not message:
            return ToolOutput(
                success=False, 
                data={}, 
                error="Message is required for notification"
            )
        
        try:
            notification_id = self._send_notification(title, message, urgency)
            
            return ToolOutput(
                success=True,
                data={
                    "notification_id": notification_id,
                    "sent_at": datetime.now().isoformat(),
                }
            )
        except Exception as e:
            self.logger.error(f"Failed to send notification: {e}")
            return ToolOutput(success=False, data={}, error=str(e))

    def _send_notification(self, title: str, message: str, urgency: str) -> str:
        """Send notification based on OS."""
        import uuid
        notification_id = str(uuid.uuid4())[:8]
        
        if sys.platform == "win32":
            # Windows: Use PowerShell with BurntToast or native
            ps_script = f'''
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

$template = @"
<toast>
    <visual>
        <binding template="ToastText02">
            <text id="1">{title}</text>
            <text id="2">{message}</text>
        </binding>
    </visual>
</toast>
"@

$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($template)
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("AI Assistant").Show($toast)
'''
            subprocess.run(
                ["powershell", "-Command", ps_script],
                capture_output=True,
                timeout=5
            )
            
        elif sys.platform == "darwin":
            # macOS: Use osascript
            applescript = f'display notification "{message}" with title "{title}"'
            subprocess.run(
                ["osascript", "-e", applescript],
                capture_output=True,
                timeout=5
            )
            
        else:
            # Linux: Use notify-send
            subprocess.run(
                ["notify-send", "-u", urgency, title, message],
                capture_output=True,
                timeout=5
            )
        
        return notification_id


# Export all tools for registration
__all__ = [
    # App tools
    "AppOpenTool",
    "AppCloseTool", 
    "AppRestartTool",
    "AppMinimizeTool",
    "AppMaximizeTool",
    "AppFocusTool",
    
    # Battery tools
    "BatteryStatusTool",
    
    # Brightness tools
    "BrightnessStatusTool",
    "BrightnessIncreaseTool",
    "BrightnessDecreaseTool",
    
    # Sound tools
    "SoundStatusTool",
    "SoundIncreaseTool",
    "SoundDecreaseTool",
    
    # Network tools
    "NetworkStatusTool",
    
    # Clipboard tools
    "ClipboardReadTool",
    "ClipboardWriteTool",
    
    # Screenshot tools
    "ScreenshotCaptureTool",
    
    # System info
    "SystemInfoTool",
    
    # Notification
    "NotificationPushTool",
]
