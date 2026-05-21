"""
message_send tool - Send a text message to a contact
"""

import asyncio

from app.plugins.tools.tool_base import BaseTool, ToolOutput
from typing import Dict, Any
from datetime import datetime
from tools.automation.whatsapp.whatsapp_automation import WhatsAppAutomation


class MessageSendTool(BaseTool):
    """Send a text message to a contact via WhatsApp

    Inputs:
    - contact (string, required): Contact name to send message to
    - message (string, required): Text message content
    - platform (string, optional): Platform: auto (from user prefs), whatsapp, facebook, slack. - (if user has no preference, default to whatsapp)

    Outputs:
    - contact (string)
    - platform_used (string)
    - sent_at (string)
    """

    TOOL_DESCRIPTION = "Send a text message to a contact"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA = {
        "contact": {
            "type": "string",
            "required": True,
            "description": "Contact name to send message to"
        },
        "message": {
            "type": "string",
            "required": True,
            "description": "Text message content"
        },
        "platform": {
            "type": "string",
            "required": False,
            "default": "auto",
            "description": "Platform: auto (from user prefs), whatsapp, facebook, slack. - (if user has no preference, default to whatsapp)"
        }
    }
    OUTPUT_SCHEMA = {
        "success": {"type": "boolean"},
        "data": {
            "contact": {"type": "string"},
            "platform_used": {"type": "string"},
            "sent_at": {"type": "string"}
        },
        "error": {"type": "string"}
    }
    EXAMPLES = [
        {"user_utterance": "send hi to Ram on WhatsApp"},
        {"user_utterance": "message John saying I'll be late"},
        {"user_utterance": "text daddy hello"},
    ]
    SEMANTIC_TAGS = ["messaging", "message", "send", "whatsapp", "text", "chat"]
    TOOL_CATEGORY = "communication"

    def get_tool_name(self) -> str:
        return "message_send"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        contact = self.get_input(inputs, "contact")
        message = self.get_input(inputs, "message")
        platform = self.get_input(inputs, "platform", "auto")
        user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "guest").strip() or "guest"

        if not contact:
            return ToolOutput(
                success=False,
                data={},
                error="Missing required parameter: contact"
            )

        if not message:
            return ToolOutput(
                success=False,
                data={},
                error="Missing required parameter: message"
            )

        try:
            # For now, we only support WhatsApp
            # Platform resolution can be extended later
            platform_used = "whatsapp"

            if platform not in ["auto", "whatsapp"]:
                self.logger.warning(f"Platform '{platform}' not supported yet, defaulting to WhatsApp")

            # Initialize WhatsApp automation
            wa = await WhatsAppAutomation.create(user_id=user_id)

            # Send the message
            sent = await asyncio.to_thread(wa.send_message, contact, message)
            if not sent:
                return ToolOutput(
                    success=False,
                    data={},
                    error="WhatsApp message send flow did not complete"
                )

            return ToolOutput(
                success=True,
                data={
                    "contact": contact,
                    "platform_used": platform_used,
                    "sent_at": datetime.utcnow().isoformat() + "Z"
                }
            )

        except RuntimeError as e:
            # WhatsApp not open or other runtime errors
            return ToolOutput(
                success=False,
                data={},
                error=str(e)
            )
        except Exception as e:
            return ToolOutput(
                success=False,
                data={},
                error=f"Failed to send message: {str(e)}"
            )
