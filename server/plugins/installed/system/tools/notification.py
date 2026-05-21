"""Notification push tool."""
import asyncio
import sys
import subprocess
import uuid
from typing import Dict, Any
from datetime import datetime

from app.plugins.tools.tool_base import BaseTool, ToolOutput


class NotificationPushTool(BaseTool):
    """Send native OS notifications."""

    TOOL_DESCRIPTION = "Send native OS notifications"
    EXECUTION_TARGET = "client"
    PARAMS_SCHEMA: Dict[str, Any] = {
        "title": {"type": "string", "required": True},
        "message": {"type": "string", "required": True},
        "urgency": {"type": "string", "required": False, "default": "normal"},
    }
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {"notification_id": {"type": "string"}, "sent_at": {"type": "string"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "send me a notification"}]
    SEMANTIC_TAGS = ["system", "notification", "push"]
    TOOL_CATEGORY = "clipboard_notify"

    def get_tool_name(self) -> str:
        return "notification_push"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        title = inputs.get("title", "Notification")
        message = inputs.get("message", "")
        urgency = self.get_input(inputs, "urgency", "normal")
        if not message:
            return ToolOutput(success=False, data={}, error="Message is required")
        try:
            notification_id = await asyncio.to_thread(self._send, title, message, urgency)
            return ToolOutput(success=True, data={"notification_id": notification_id, "sent_at": datetime.now().isoformat()})
        except Exception as e:
            return ToolOutput(success=False, data={}, error=str(e))

    def _send(self, title: str, message: str, urgency: str) -> str:
        nid = str(uuid.uuid4())[:8]
        if sys.platform == "win32":
            ps_script = f'''
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$template = @"
<toast><visual><binding template="ToastText02"><text id="1">{title}</text><text id="2">{message}</text></binding></visual></toast>
"@
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($template)
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("AI Assistant").Show($toast)
'''
            subprocess.run(["powershell", "-Command", ps_script], capture_output=True, timeout=5)
        elif sys.platform == "darwin":
            subprocess.run(["osascript", "-e", f'display notification "{message}" with title "{title}"'], capture_output=True, timeout=5)
        else:
            subprocess.run(["notify-send", "-u", urgency, title, message], capture_output=True, timeout=5)
        return nid


__all__ = ["NotificationPushTool"]
