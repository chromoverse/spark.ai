"""
message_file tool - Send a document or file to a contact
"""

from ..base import BaseTool, ToolOutput
from typing import Dict, Any
from datetime import datetime
from app.agent.shared.automation.whatsapp.whatsapp_automation import WhatsAppAutomation
import os


class MessageFileTool(BaseTool):
    """Send a document or file (PDF, ZIP, DOCX, etc.) to a contact via WhatsApp"""
    
    def get_tool_name(self) -> str:
        return "message_file"
    
    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        contact = self.get_input(inputs, "contact")
        file_path = self.get_input(inputs, "file_path")
        caption = self.get_input(inputs, "caption", "")
        platform = self.get_input(inputs, "platform", "auto")
        
        if not contact:
            return ToolOutput(
                success=False,
                data={},
                error="Missing required parameter: contact"
            )
        
        if not file_path:
            return ToolOutput(
                success=False,
                data={},
                error="Missing required parameter: file_path"
            )
        
        # Validate file exists
        if not os.path.exists(file_path):
            return ToolOutput(
                success=False,
                data={},
                error=f"File not found: {file_path}"
            )
        
        try:
            # For now, we only support WhatsApp
            platform_used = "whatsapp"
            
            if platform not in ["auto", "whatsapp"]:
                self.logger.warning(f"Platform '{platform}' not supported yet, defaulting to WhatsApp")
            
            # Initialize WhatsApp automation
            wa = await WhatsAppAutomation().create()
            
            # Send the file
            wa.send_file(contact, file_path, caption)
            
            # Get file name from path
            file_name = os.path.basename(file_path)
            
            return ToolOutput(
                success=True,
                data={
                    "contact": contact,
                    "file_name": file_name,
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
                error=f"Failed to send file: {str(e)}"
            )
