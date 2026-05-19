"""
call_audio tool - Start an audio call with a contact
"""

import asyncio

from ..base import BaseTool, ToolOutput
from typing import Dict, Any
from datetime import datetime
from tools.automation.whatsapp.whatsapp_automation import WhatsAppAutomation


class CallAudioTool(BaseTool):
    """Start an audio call with a contact via WhatsApp

    Inputs:
    - contact (string, required): Contact name to call
    - platform (string, optional)

    Outputs:
    - contact (string)
    - platform_used (string)
    - started_at (string)
    """
    
    def get_tool_name(self) -> str:
        return "call_audio"
    
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
           
            # Start audio call
            started = await asyncio.to_thread(wa.audio_call, contact)
            if not started:
                return ToolOutput(
                    success=False,
                    data={},
                    error="WhatsApp audio call flow did not complete"
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
                error=f"Failed to start audio call: {str(e)}"
            )
