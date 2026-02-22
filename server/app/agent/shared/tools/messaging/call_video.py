"""
call_video tool - Start a video call with a contact
"""

from ..base import BaseTool, ToolOutput
from typing import Dict, Any
from datetime import datetime
from app.agent.shared.automation.whatsapp.whatsapp_automation import WhatsAppAutomation


class CallVideoTool(BaseTool):
    """Start a video call with a contact via WhatsApp"""
    
    def get_tool_name(self) -> str:
        return "call_video"
    
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
            wa = await WhatsAppAutomation().create()
            
            # Start video call
            wa.video_call(contact)
            
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
