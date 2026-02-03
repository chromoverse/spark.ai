import asyncio
import logging
import time
from typing import AsyncGenerator
import io
import wave
import numpy as np
from app.services.tts.base import TTSEngine

logger = logging.getLogger(__name__)

class KokoroEngine(TTSEngine):
    """
    Kokoro TTS Engine (PyTorch based)
    """
    
    def __init__(self):
        self._pipeline = None
        self._initialized = False
        self._lock = asyncio.Lock()
        
    def get_engine_name(self) -> str:
        return "kokoro"
        
    async def is_available(self) -> bool:
        if not self._initialized:
            await self._initialize()
        return self._initialized
        
    async def _initialize(self):
        async with self._lock:
            if self._initialized:
                return
            try:
                from kokoro import KPipeline
                import torch
                
                logger.info("🔥 Initializing Kokoro Pipeline...")
                start = time.time()
                # Initialize with American English by default
                self._pipeline = KPipeline(lang_code="a") 
                logger.info(f"✅ Kokoro initialized in {time.time() - start:.2f}s")
                self._initialized = True
            except ImportError:
                logger.error("❌ Kokoro not installed")
                self._initialized = False
            except Exception as e:
                logger.error(f"❌ Kokoro init failed: {e}")
                self._initialized = False

    def _pcm_to_wav(self, pcm_data: bytes, sample_rate: int = 24000) -> bytes:
        """Convert PCM bytes to WAV format"""
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_data)
        buffer.seek(0)
        return buffer.read()

    async def generate_stream(
        self, 
        text: str, 
        voice: str, 
        speed: float, 
        lang: str
    ) -> AsyncGenerator[bytes, None]:
        
        if not await self.is_available():
            raise RuntimeError("Kokoro engine not available")
            
        try:
            # Map simplified lang codes to Kokoro codes if needed
            # For now assuming 'a' (American English)
            
            # Run generation in executor to avoid blocking event loop
            def _generate():
                return list(self._pipeline(text, voice=voice, speed=speed))
            
            logger.info(f"🎤 Kokoro generating: {text[:30]}...")
            
            # This returns a list of (graphemes, phonemes, audio)
            results = await asyncio.get_event_loop().run_in_executor(None, _generate)
            
            for _, _, audio_tensor in results:
                # Convert to numpy/bytes
                if hasattr(audio_tensor, 'cpu'):
                    audio_numpy = audio_tensor.cpu().numpy()
                else:
                    audio_numpy = audio_tensor
                    
                # Convert float32 to int16 PCM
                pcm_data = (audio_numpy * 32767).astype(np.int16).tobytes()
                
                # Convert to WAV chunk (simplified: actually better to stream raw PCM or complete WAV)
                # But for browser compatibility, individual WAV chunks might not play smoothly 
                # unless handled continuously. 
                # For this implementation, we'll yield WAV chunks which the frontend needs to handle,
                # OR we send PCM and let a manager handle wrapping.
                # Per previous `tts_services.py`, it was sending WAV chunks.
                
                wav_chunk = self._pcm_to_wav(pcm_data, 24000)
                yield wav_chunk
                
        except Exception as e:
            logger.error(f"❌ Kokoro generation error: {e}")
            raise
