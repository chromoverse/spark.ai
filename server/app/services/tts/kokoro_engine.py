import asyncio
import logging
import time
from typing import Any, AsyncGenerator, Dict, Optional
import io
import wave
import numpy as np
from app.services.tts.base import TTSEngine

logger = logging.getLogger(__name__)

# Kokoro lang_code mapping (user-facing lang → Kokoro internal code)
_KOKORO_LANG_MAP: Dict[str, str] = {
    # Hindi
    "hi": "h", "hindi": "h",
    # English (default)
    "en": "a", "en-us": "a", "english": "a",
    # British English
    "en-gb": "b",
    # Japanese
    "ja": "j", "japanese": "j",
    # Chinese (Mandarin)
    "zh": "z", "chinese": "z",
    # Spanish
    "es": "e", "spanish": "e",
    # French
    "fr": "f", "french": "f",
    # Italian
    "it": "i", "italian": "i",
    # Portuguese (Brazilian)
    "pt": "p", "pt-br": "p", "portuguese": "p",
}


class KokoroEngine(TTSEngine):
    """
    Kokoro TTS Engine (PyTorch based).

    Maintains one KPipeline per language so that each language uses
    the correct phonemizer (e.g. lang_code='h' for Hindi).
    The default English pipeline is created at init time;
    other pipelines are created lazily on first use.
    """

    def __init__(self) -> None:
        self._pipelines: Dict[str, Any] = {}  # kokoro_lang_code → KPipeline
        self._initialized: bool = False
        self._lock: asyncio.Lock = asyncio.Lock()

    def get_engine_name(self) -> str:
        return "kokoro"

    async def is_available(self) -> bool:
        if not self._initialized:
            await self._initialize()
        return self._initialized

    async def _initialize(self) -> None:
        """Pre-create the default English pipeline."""
        async with self._lock:
            if self._initialized:
                return
            try:
                from kokoro import KPipeline

                logger.info("🔥 Initializing Kokoro Pipeline (English)...")
                start = time.time()
                self._pipelines["a"] = KPipeline(lang_code="a")
                logger.info(f"✅ Kokoro (English) initialized in {time.time() - start:.2f}s")
                self._initialized = True
            except ImportError:
                logger.error("❌ Kokoro not installed")
                self._initialized = False
            except Exception as e:
                logger.error(f"❌ Kokoro init failed: {e}")
                self._initialized = False

    def _get_pipeline(self, lang: str) -> Any:
        """
        Return the KPipeline for the given language, creating it if needed.

        Args:
            lang: User-facing language code (e.g. 'hi', 'en', 'ja').

        Returns:
            The KPipeline instance for the resolved Kokoro lang_code.
        """
        kokoro_code = _KOKORO_LANG_MAP.get(lang.lower().strip(), "a")

        if kokoro_code not in self._pipelines:
            from kokoro import KPipeline

            logger.info(f"🔥 Creating Kokoro pipeline for lang_code='{kokoro_code}' (from '{lang}')...")
            start = time.time()
            self._pipelines[kokoro_code] = KPipeline(lang_code=kokoro_code)
            logger.info(f"✅ Kokoro pipeline '{kokoro_code}' ready in {time.time() - start:.2f}s")

        return self._pipelines[kokoro_code]

    @staticmethod
    def _pcm_to_wav(pcm_data: bytes, sample_rate: int = 24000) -> bytes:
        """Convert PCM bytes to a complete, valid WAV file."""
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
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
        lang: str,
    ) -> AsyncGenerator[bytes, None]:

        if not await self.is_available():
            raise RuntimeError("Kokoro engine not available")

        try:
            pipeline = self._get_pipeline(lang)

            # Run generation in executor to avoid blocking event loop
            def _generate() -> list:
                return list(pipeline(text, voice=voice, speed=speed))

            logger.info(
                f"🎤 Kokoro generating (lang='{lang}', "
                f"kokoro_code='{_KOKORO_LANG_MAP.get(lang.lower().strip(), 'a')}'): "
                f"{text[:50]}..."
            )

            # Returns a list of (graphemes, phonemes, audio_tensor)
            results = await asyncio.get_event_loop().run_in_executor(None, _generate)

            for _, _, audio_tensor in results:
                # Convert to numpy
                if hasattr(audio_tensor, "cpu"):
                    audio_numpy = audio_tensor.cpu().numpy()
                else:
                    audio_numpy = audio_tensor

                # float32 → int16 PCM → WAV
                pcm_data = (audio_numpy * 32767).astype(np.int16).tobytes()
                wav_chunk = self._pcm_to_wav(pcm_data, 24000)
                yield wav_chunk

        except Exception as e:
            logger.error(f"❌ Kokoro generation error: {e}")
            raise
