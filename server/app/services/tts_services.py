import asyncio
import logging
import time
import uuid
from typing import AsyncGenerator, Optional, Any
from app.services.tts.manager import tts_manager
from app.services.tts.voice_selector import VoiceSelector

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

    def select_voice(self, gender: Optional[str], lang: str = "en") -> str:
        """
        Main public voice selector for TTS.

        Accepts:
        - gender: ``male`` or ``female`` (anything else falls back to language default)
        - lang: language code, defaults to English
        """
        normalized_lang = (lang or "en").strip().lower() or "en"
        normalized_gender = (gender or "").strip().lower() if gender else None
        if normalized_gender not in {"male", "female"}:
            normalized_gender = None

        voice = VoiceSelector.get_voice(
            lang=normalized_lang,
            gender=normalized_gender,
            randomize=False,
        )
        logger.debug(
            "🎙️ Voice selected: lang=%s gender=%s voice=%s",
            normalized_lang,
            normalized_gender or "default",
            voice,
        )
        return voice

    async def generate_audio_stream(
        self,
        text: str,
        voice: Optional[str] = None,
        rate: Optional[str] = None,
        pitch: Optional[str] = None,
        lang: Optional[str] = None,
        gender: Optional[str] = None,
        prefer_low_latency: bool = False,
    ) -> AsyncGenerator[bytes, None]:
        """Generate audio stream — yields individual valid WAV chunks."""
        resolved_lang = (lang or "en").strip().lower() or "en"
        resolved_voice = voice or self.select_voice(gender=gender, lang=resolved_lang)

        speed = 1.0
        if rate:
            try:
                val = float(rate.replace("%", "").replace("+", ""))
                speed = 1.0 + (val / 100.0)
            except Exception:
                pass

        async for chunk in tts_manager.generate_stream(
            text=text,
            voice=resolved_voice,
            speed=speed,
            lang=resolved_lang,
            gender=gender,
            prefer_low_latency=prefer_low_latency,
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
        prefer_low_latency: bool = False,
    ) -> bool:
        """
        Stream TTS audio to a WebSocket client.

        Each event carries a unique ``stream_id`` so the client can associate
        chunks with the correct stream and reject stale data.
        """
        request_started = time.perf_counter()
        text_char_count = len(text or "")
        text_word_count = len((text or "").split())
        if await self._is_duplicate_request(sid=sid, text=text):
            logger.info("⚠️ Skipping duplicate TTS stream for sid=%s text='%s'", sid, text[:80])
            return True

        stream_id = uuid.uuid4().hex[:12]
        logger.info(
            "🔌 TTS stream [%s] to %s words=%d chars=%d",
            stream_id,
            sid,
            text_word_count,
            text_char_count,
        )

        emit_start_t0 = time.perf_counter()
        await sio.emit("tts-start", {"text": text, "streamId": stream_id}, to=sid)
        logger.info(
            "⏱️ TTS stream [%s] emitted tts-start in %.0fms",
            stream_id,
            (time.perf_counter() - emit_start_t0) * 1000,
        )

        try:
            chunk_count = 0
            first_chunk_ms: Optional[float] = None
            async for audio_bytes in self.generate_audio_stream(
                text, voice, rate, lang=lang, gender=gender, prefer_low_latency=prefer_low_latency
            ):
                if first_chunk_ms is None:
                    first_chunk_ms = (time.perf_counter() - request_started) * 1000
                await sio.emit(
                    "tts-chunk",
                    {"streamId": stream_id, "data": audio_bytes},
                    to=sid,
                )
                chunk_count += 1

                if chunk_delay > 0:
                    await asyncio.sleep(chunk_delay)

            total_ms = (time.perf_counter() - request_started) * 1000
            logger.info(
                "✅ TTS metrics stream_id=%s sid=%s first_chunk_ms=%s total_ms=%.0f chunks=%d words=%d chars=%d low_latency=%s",
                stream_id,
                sid,
                f"{first_chunk_ms:.0f}" if first_chunk_ms is not None else "na",
                total_ms,
                chunk_count,
                text_word_count,
                text_char_count,
                prefer_low_latency,
            )
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
