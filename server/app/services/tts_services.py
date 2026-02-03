import asyncio
import logging
from typing import AsyncGenerator, Optional, Dict, Any
from app.services.tts.manager import tts_manager

logger = logging.getLogger(__name__)

class TTSService:
    """
    Unified TTS service facade.
    Delegates to TTSManager for engine handling and fallback logic.
    """
    
    def __init__(self):
        # Manager self-initializes on first use
        pass
        
    async def generate_audio_stream(
        self, 
        text: str, 
        voice: Optional[str] = None,
        rate: Optional[str] = None, # Legacy param compatibility
        pitch: Optional[str] = None, # Legacy param compatibility
        lang: Optional[str] = None,
        gender: Optional[str] = None
    ) -> AsyncGenerator[bytes, None]:
        """
        Generate audio stream.
        """
        # Convert rate string (e.g., "+15%") to float speed (e.g., 1.15) if needed
        speed = 1.0
        if rate:
            try:
                # Simple parsing: remove %, convert to float
                val = float(rate.replace("%", "").replace("+", ""))
                speed = 1.0 + (val / 100.0)
            except:
                pass
                
        async for chunk in tts_manager.generate_stream(
            text=text, 
            voice=voice, 
            speed=speed, 
            lang=lang,
            gender=gender
        ):
            yield chunk

    async def stream_to_socket(
        self,
        sio: Any,
        sid: str,
        text: str,
        voice: Optional[str] = None,
        rate: Optional[str] = None,
        lang: Optional[str] = None,
        gender: Optional[str] = None,
        chunk_delay: float = 0.0
    ) -> bool:
        """
        Stream TTS audio to a WebSocket client.
        """
        logger.info(f"🔌 TTS Streaming to socket {sid}")
        
        await sio.emit("tts-start", {"text": text}, to=sid)
        
        try:
            chunk_count = 0
            async for audio_bytes in self.generate_audio_stream(text, voice, rate, lang=lang, gender=gender):
                await sio.emit("tts-chunk", audio_bytes, to=sid)
                chunk_count += 1
                
                if chunk_delay > 0:
                    await asyncio.sleep(chunk_delay)
            
            logger.info(f"✅ Streamed {chunk_count} chunks to {sid}")
            await sio.emit("tts-end", {"success": True, "chunks": chunk_count}, to=sid)
            return True
            
        except Exception as e:
            logger.exception(f"❌ Stream error: {e}")
            await sio.emit("tts-end", {"success": False, "error": str(e)}, to=sid)
            return False
            
    async def generate_complete_audio(self, text: str, **kwargs) -> bytes:
        """Generate complete audio bytes"""
        chunks = []
        async for chunk in self.generate_audio_stream(text, **kwargs):
            chunks.append(chunk)
        return b"".join(chunks)


# Singleton instance
tts_service = TTSService()