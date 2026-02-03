import asyncio
import logging
import io
from typing import AsyncGenerator
from app.services.tts.base import TTSEngine

logger = logging.getLogger(__name__)

class GTTSEngine(TTSEngine):
    """
    Google TTS Engine (gTTS)
    """
    
    def get_engine_name(self) -> str:
        return "gtts"
        
    async def is_available(self) -> bool:
        try:
            import gtts
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
            from gtts import gTTS
        except ImportError:
            raise RuntimeError("gTTS not installed")
            
        logger.info(f"🎤 gTTS generating: lang={lang}")
        
        def _generate():
            tts = gTTS(text=text, lang=lang, slow=False)
            fp = io.BytesIO()
            tts.write_to_fp(fp)
            fp.seek(0)
            return fp
            
        # gTTS is blocking/network bound
        fp = await asyncio.get_event_loop().run_in_executor(None, _generate)
        
        chunk_size = 4096
        while True:
            chunk = fp.read(chunk_size)
            if not chunk:
                break
            yield chunk
