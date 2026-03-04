
from typing import Dict, Any
from datetime import datetime

from ..base import BaseTool, ToolOutput

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

