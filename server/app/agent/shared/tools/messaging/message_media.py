"""
message_media tool - Send a photo or video to a contact
"""

from ..base import BaseTool, ToolOutput
from typing import Dict, Any
from datetime import datetime
from app.agent.shared.automation.whatsapp.whatsapp_automation import WhatsAppAutomation
import os


class MessageMediaTool(BaseTool):
    """Send a photo or video to a contact via WhatsApp"""
    
    def get_tool_name(self) -> str:
        return "message_media"
    
    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        contact = self.get_input(inputs, "contact")
        media_path = self.get_input(inputs, "media_path")
        caption = self.get_input(inputs, "caption", "")
        platform = self.get_input(inputs, "platform", "auto")
        
        if not contact:
            return ToolOutput(
                success=False,
                data={},
                error="Missing required parameter: contact"
            )
        
        if not media_path:
            return ToolOutput(
                success=False,
                data={},
                error="Missing required parameter: media_path"
            )
        
        # Validate media file exists
        if not os.path.exists(media_path):
            return ToolOutput(
                success=False,
                data={},
                error=f"Media file not found: {media_path}"
            )
        
        try:
            # For now, we only support WhatsApp
            platform_used = "whatsapp"
            
            if platform not in ["auto", "whatsapp"]:
                self.logger.warning(f"Platform '{platform}' not supported yet, defaulting to WhatsApp")
            
            # Determine media type from extension
            _, ext = os.path.splitext(media_path.lower())
            photo_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']
            video_extensions = ['.mp4', '.mov', '.avi', '.mkv', '.webm']
            
            if ext in photo_extensions:
                media_type = "photo"
            elif ext in video_extensions:
                media_type = "video"
            else:
                media_type = "unknown"
            
            # Initialize WhatsApp automation
            wa = WhatsAppAutomation()
            
            # Send the media (photo/video)
            wa.send_photo(contact, media_path, caption)
            
            return ToolOutput(
                success=True,
                data={
                    "contact": contact,
                    "media_type": media_type,
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
                error=f"Failed to send media: {str(e)}"
            )

