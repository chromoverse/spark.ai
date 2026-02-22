"""
message_send tool - Send a text message to a contact
"""

from ..base import BaseTool, ToolOutput
from typing import Dict, Any
from datetime import datetime
from app.agent.shared.automation.whatsapp.whatsapp_automation import WhatsAppAutomation


class MessageSendTool(BaseTool):
    """Send a text message to a contact via WhatsApp"""
    
    def get_tool_name(self) -> str:
        return "message_send"
    
    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        contact = self.get_input(inputs, "contact")
        message = self.get_input(inputs, "message")
        platform = self.get_input(inputs, "platform", "auto")
        
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
            wa = WhatsAppAutomation()
            
            # Send the message
            wa.send_message(contact, message)
            
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
