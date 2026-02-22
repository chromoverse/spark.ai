"""
call_audio tool - Start an audio call with a contact
"""

from ..base import BaseTool, ToolOutput
from typing import Dict, Any
from datetime import datetime
from app.agent.shared.automation.whatsapp.whatsapp_automation import WhatsAppAutomation


class CallAudioTool(BaseTool):
    """Start an audio call with a contact via WhatsApp"""
    
    def get_tool_name(self) -> str:
        return "call_audio"
    
    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        contact = self.get_input(inputs, "contact")
        platform = self.get_input(inputs, "platform", "auto")
        
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
            wa = WhatsAppAutomation()
            
            # Start audio call
            wa.audio_call(contact)
            
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
