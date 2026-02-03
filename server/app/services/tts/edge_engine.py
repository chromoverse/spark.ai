import asyncio
import logging
from typing import AsyncGenerator
from app.services.tts.base import TTSEngine

logger = logging.getLogger(__name__)

class EdgeEngine(TTSEngine):
    """
    Edge TTS Engine (Microsoft Edge Read Aloud)
    """
    
    def get_engine_name(self) -> str:
        return "edge-tts"
        
    async def is_available(self) -> bool:
        try:
            import edge_tts
            return True
        except ImportError:
            return False
            
    async def generate_stream(
        self, 
        text: str, 
        voice: str, 
        speed: float, 
        lang: str
    ) -> AsyncGenerator[bytes, None]:
        
        try:
            import edge_tts
        except ImportError:
            raise RuntimeError("edge-tts not installed")
            
        rate_str = f"+{int((speed - 1.0) * 100)}%" if speed != 1.0 else "+0%"
        
        logger.info(f"🎤 EdgeTTS generating: voice={voice}, rate={rate_str}")
        
        communicate = edge_tts.Communicate(text, voice, rate=rate_str)
        
        try:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    yield chunk["data"]
        except Exception as e:
            # Handle the 403 error gracefully by logging
            if "403" in str(e):
                logger.error("❌ EdgeTTS 403 Forbidden - Microsoft has blocked access")
            raise
