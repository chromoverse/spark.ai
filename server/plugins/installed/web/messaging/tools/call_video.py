"""
call_video tool - Start a video call with a contact
"""

import asyncio

from app.plugins.tools.tool_base import BaseTool, ToolOutput
from typing import Dict, Any
from datetime import datetime
from tools.automation.whatsapp.whatsapp_automation import WhatsAppAutomation


class CallVideoTool(BaseTool):
    """Start a video call with a contact via WhatsApp

    Inputs:
    - contact (string, required): Contact name to video call
    - platform (string, optional)

    Outputs:
    - contact (string)
    - platform_used (string)
    - started_at (string)
    """

    TOOL_DESCRIPTION = "Start a video call with a contact"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA = {
        "contact": {
            "type": "string",
            "required": True,
            "description": "Contact name to video call"
        },
        "platform": {
            "type": "string",
            "required": False,
            "default": "auto"
        }
    }
    OUTPUT_SCHEMA = {
        "success": {"type": "boolean"},
        "data": {
            "contact": {"type": "string"},
            "platform_used": {"type": "string"},
            "started_at": {"type": "string"}
        },
        "error": {"type": "string"}
    }
    EXAMPLES = [
        {"user_utterance": "video call mom on WhatsApp"},
        {"user_utterance": "facetime John"},
        {"user_utterance": "video call daddy"},
    ]
    SEMANTIC_TAGS = ["messaging", "call", "video", "whatsapp", "facetime"]
    TOOL_CATEGORY = "communication"

    def get_tool_name(self) -> str:
        return "call_video"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        contact = self.get_input(inputs, "contact")
        platform = self.get_input(inputs, "platform", "auto")
        user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "guest").strip() or "guest"

        if not contact:
            return ToolOutput(
                success=False,
                data={},
                error="Missing required parameter: contact"
            )

        try:
            # For now, we only support WhatsApp
            platform_used = "whatsapp"

            if platform not in ["auto", "whatsapp"]:
                self.logger.warning(f"Platform '{platform}' not supported yet, defaulting to WhatsApp")

            # Initialize WhatsApp automation
            wa = await WhatsAppAutomation.create(user_id=user_id)

            # Start video call
            started = await asyncio.to_thread(wa.video_call, contact)
            if not started:
                return ToolOutput(
                    success=False,
                    data={},
                    error="WhatsApp video call flow did not complete"
                )

            return ToolOutput(
                success=True,
                data={
                    "contact": contact,
                    "platform_used": platform_used,
                    "started_at": datetime.utcnow().isoformat() + "Z"
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
                error=f"Failed to start video call: {str(e)}"
            )
