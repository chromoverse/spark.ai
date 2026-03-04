import asyncio
import logging
import time
import uuid
from typing import AsyncGenerator, Optional, Dict, Any
from app.services.tts.manager import tts_manager

logger = logging.getLogger(__name__)


class TTSService:
    """
    Unified TTS service facade.
    Delegates to TTSManager for engine handling and fallback logic.
    """

    def __init__(self) -> None:
        # Prevent accidental double-play for the same user/text arriving nearly together.
        self._recent_requests: dict[tuple[str, str], float] = {}
        self._dedupe_window_seconds = 1.25
        self._recent_window_seconds = 12.0
        self._dedupe_lock = asyncio.Lock()

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join(text.strip().lower().split())

    async def _is_duplicate_request(self, sid: str, text: str) -> bool:
        normalized = self._normalize_text(text)
        if not normalized:
            return False

        now = time.monotonic()
        key = (sid, normalized)

        async with self._dedupe_lock:
            # Keep map bounded by pruning stale entries.
            stale_before = now - self._recent_window_seconds
            for req_key, ts in list(self._recent_requests.items()):
                if ts < stale_before:
                    del self._recent_requests[req_key]

            previous = self._recent_requests.get(key)
            self._recent_requests[key] = now

        return previous is not None and (now - previous) <= self._dedupe_window_seconds

    async def warmup_tts_engine(self) -> bool:
        """
        Warmup the TTS engine (Kokoro) by pre-initializing it.
        Should be called during application startup.
        """
        try:
            logger.info("🔥 Warming up TTS engine (Kokoro)...")
            await tts_manager.initialize()
            logger.info("✅ TTS engine warmup complete")
            return True
        except Exception as e:
            logger.error(f"❌ TTS engine warmup failed: {e}")
            return False

    async def generate_audio_stream(
        self,
        text: str,
        voice: Optional[str] = None,
        rate: Optional[str] = None,
        pitch: Optional[str] = None,
        lang: Optional[str] = None,
        gender: Optional[str] = None,
    ) -> AsyncGenerator[bytes, None]:
        """Generate audio stream — yields individual valid WAV chunks."""
        speed = 1.0
        if rate:
            try:
                val = float(rate.replace("%", "").replace("+", ""))
                speed = 1.0 + (val / 100.0)
            except Exception:
                pass

        async for chunk in tts_manager.generate_stream(
            text=text,
            voice=voice,
            speed=speed,
            lang=lang,
            gender=gender,
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
        chunk_delay: float = 0.0,
    ) -> bool:
        """
        Stream TTS audio to a WebSocket client.

        Each event carries a unique ``stream_id`` so the client can associate
        chunks with the correct stream and reject stale data.
        """
        if await self._is_duplicate_request(sid=sid, text=text):
            logger.info("⚠️ Skipping duplicate TTS stream for sid=%s text='%s'", sid, text[:80])
            return True

        stream_id = uuid.uuid4().hex[:12]
        logger.info(f"🔌 TTS stream [{stream_id}] to {sid}")

        await sio.emit("tts-start", {"text": text, "streamId": stream_id}, to=sid)

        try:
            chunk_count = 0
            async for audio_bytes in self.generate_audio_stream(
                text, voice, rate, lang=lang, gender=gender
            ):
                await sio.emit(
                    "tts-chunk",
                    {"streamId": stream_id, "data": audio_bytes},
                    to=sid,
                )
                chunk_count += 1

                if chunk_delay > 0:
                    await asyncio.sleep(chunk_delay)

            logger.info(f"✅ Stream [{stream_id}] sent {chunk_count} chunks to {sid}")
            await sio.emit(
                "tts-end",
                {"success": True, "chunks": chunk_count, "streamId": stream_id},
                to=sid,
            )
            return True

        except Exception as e:
            logger.exception(f"❌ Stream [{stream_id}] error: {e}")
            await sio.emit(
                "tts-end",
                {"success": False, "error": str(e), "streamId": stream_id},
                to=sid,
            )
            return False

    async def generate_complete_audio(self, text: str, **kwargs: Any) -> bytes:
        """Generate complete audio bytes (concatenated WAV chunks)."""
        chunks: list[bytes] = []
        async for chunk in self.generate_audio_stream(text, **kwargs):
            chunks.append(chunk)
        return b"".join(chunks)


# Singleton instance
tts_service = TTSService()
