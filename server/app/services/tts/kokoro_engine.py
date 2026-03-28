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
        self._bg_tasks: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

        # Kick off background load for default English to be ready early, non-blocking
        try:
            import kokoro
            self._bg_tasks["a"] = asyncio.create_task(self._preload_pipeline("a"))
        except ImportError:
            pass

    def get_engine_name(self) -> str:
        return "kokoro"

    async def is_available(self) -> bool:
        """Fast check to see if we can use this engine (doesn't block on weights load)."""
        try:
            import kokoro
            return True
        except ImportError:
            return False

    async def _preload_pipeline(self, lang_code: str) -> None:
        """Background worker to load a pipeline."""
        def _load():
            from kokoro import KPipeline
            start = time.time()
            return KPipeline(lang_code=lang_code), time.time() - start

        try:
            logger.info(f"🔥 [Background] Loading Kokoro Pipeline ({lang_code})...")
            pipeline, elapsed = await asyncio.get_event_loop().run_in_executor(None, _load)
            async with self._lock:
                self._pipelines[lang_code] = pipeline
            logger.info(f"✅ [Background] Kokoro ({lang_code}) ready in {elapsed:.2f}s")
        except Exception as e:
            logger.error(f"❌ Kokoro background init failed: {e}")

    async def _get_pipeline(self, lang: str) -> Any:
        """
        Return the KPipeline for the given language, creating it lazily if needed.
        """
        kokoro_code = _KOKORO_LANG_MAP.get(lang.lower().strip(), "a")

        async with self._lock:
            if kokoro_code in self._pipelines:
                return self._pipelines[kokoro_code]

        # If it's preloading in background, wait for it
        if kokoro_code in self._bg_tasks and not self._bg_tasks[kokoro_code].done():
            logger.info(f"⏳ Waiting for background Kokoro load ({kokoro_code})...")
            await self._bg_tasks[kokoro_code]
            async with self._lock:
                if kokoro_code in self._pipelines:
                    return self._pipelines[kokoro_code]

        # Otherwise, fully load it via executor now
        def _load():
            from kokoro import KPipeline
            start = time.time()
            return KPipeline(lang_code=kokoro_code), time.time() - start

        try:
            logger.info(f"🔥 Creating Kokoro pipeline lazy ('{kokoro_code}', from '{lang}')...")
            pipeline, elapsed = await asyncio.get_event_loop().run_in_executor(None, _load)
            async with self._lock:
                self._pipelines[kokoro_code] = pipeline
            logger.info(f"✅ Kokoro pipeline '{kokoro_code}' lazy loaded in {elapsed:.2f}s")
        except Exception as e:
            logger.error(f"❌ Kokoro lazy init failed: {e}")
            raise RuntimeError(f"Kokoro lazy init failed: {e}")

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
            pipeline = await self._get_pipeline(lang)

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
