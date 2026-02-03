import logging
import asyncio
from typing import AsyncGenerator, List, Optional
from app.services.tts.base import TTSEngine
from app.services.tts.kokoro_engine import KokoroEngine
from app.services.tts.edge_engine import EdgeEngine
from app.services.tts.gtts_engine import GTTSEngine
from app.services.tts.voice_selector import VoiceSelector

logger = logging.getLogger(__name__)

class TTSManager:
    """
    Manages TTS engines with fallback priority:
    1. Kokoro (Local, Fast, High Quality)
    2. Edge TTS (Cloud, High Quality, Free - currently unstable)
    3. gTTS (Cloud, Standard Quality, Free)
    """
    
    def __init__(self):
        self.engines: List[TTSEngine] = []
        self._initialized = False
        
    async def initialize(self):
        """Initialize all engines"""
        if self._initialized:
            return
            
        # Priority 1: Kokoro
        kokoro = KokoroEngine()
        if await kokoro.is_available():
            self.engines.append(kokoro)
            logger.info("✅ TTS: Kokoro engine enabled")
            
        # Priority 2: Edge TTS
        edge = EdgeEngine()
        if await edge.is_available():
            self.engines.append(edge)
            logger.info("✅ TTS: Edge engine enabled")
            
        # Priority 3: gTTS
        gtts = GTTSEngine()
        if await gtts.is_available():
            self.engines.append(gtts)
            logger.info("✅ TTS: gTTS engine enabled")
            
        self._initialized = True
        
    async def generate_stream(
        self, 
        text: str, 
        voice: Optional[str] = None, 
        speed: float = 1.0, 
        lang: Optional[str] = None,
        gender: Optional[str] = None
    ) -> AsyncGenerator[bytes, None]:
        """
        Generate audio using the first working engine
        """
        if not self._initialized:
            await self.initialize()
            
        # Auto-detect language if not provided
        if not lang:
            lang = VoiceSelector.detect_language(text)
            
        # Select best voice if not provided
        if not voice:
            # Note: VoiceSelector returns Kokoro-compatible voice IDs mostly
            voice = VoiceSelector.get_voice(lang, gender)
            
        last_error = None
        
        for engine in self.engines:
            engine_name = engine.get_engine_name()
            
            # Skip if engine doesn't support the language? 
            # For now we assume engines are versatile or will fail gracefully
            
            try:
                # logger.debug(f"🔄 Attempting TTS with {engine_name}...")
                
                async for chunk in engine.generate_stream(text, voice, speed, lang):
                    yield chunk
                
                return
                
            except Exception as e:
                logger.warning(f"⚠️ TTS {engine_name} failed: {e}")
                last_error = e
                continue
                
        # If we get here, all engines failed
        logger.error("❌ All TTS engines failed")
        if last_error:
            raise last_error
        else:
            raise RuntimeError("No TTS engines available")
            
    # Singleton access
    @classmethod
    def get_instance(cls):
        if not hasattr(cls, "_instance"):
            cls._instance = cls()
        return cls._instance

# Global instance
tts_manager = TTSManager()
