"""
Groq TTS Engine — Cloud-based Text-to-Speech via Groq API.

Uses the Groq SDK to call ``audio.speech.create()`` with the
Orpheus model.  Returns a complete WAV blob that gets yielded
as a single chunk through the standard TTSEngine interface.

Key rotation uses the same ``_KeyCache`` / ``key_manager`` system
as the LLM providers.
"""

import asyncio
import io
import logging
from typing import AsyncGenerator, Optional

from groq import Groq  # type: ignore[import-untyped]
from app.services.tts.base import TTSEngine
from app.ai.providers.key_manager import get_next_key, rotate_key

logger = logging.getLogger(__name__)

# ── Groq Orpheus config ────────────────────────────────────────────────────
GROQ_TTS_MODEL = "canopylabs/orpheus-v1-english"
GROQ_TTS_FORMAT = "wav"

# Available voices: autumn, diana, hannah, austin, daniel, troy
GROQ_VOICE_MAP = {
    "male":   "daniel",
    "female": "autumn",
}
GROQ_DEFAULT_VOICE = "autumn"

# Errors that mean this key is done → rotate
_QUOTA_KEYWORDS = frozenset({
    "rate_limit", "resource_exhausted", "quota", "429",
    "insufficient_quota", "billing",
})


def _is_quota_error(err: Exception) -> bool:
    msg = str(err).lower()
    return any(kw in msg for kw in _QUOTA_KEYWORDS)


class GroqEngine(TTSEngine):
    """
    Groq TTS via Orpheus — fastest cloud TTS option.

    The Groq SDK is synchronous, so all API calls are wrapped in
    ``asyncio.to_thread`` to keep the event loop free.
    """

    def get_engine_name(self) -> str:
        return "groq-tts"

    async def is_available(self) -> bool:
        key = get_next_key("groq")
        return key is not None

    async def generate_stream(
        self,
        text: str,
        voice: str,
        speed: float,
        lang: str,
    ) -> AsyncGenerator[bytes, None]:
        """
        Generate audio via Groq Orpheus.

        Yields a single WAV blob (Groq returns the full file at once).
        The voice param coming in is usually a Kokoro voice ID —
        we remap it based on gender heuristics or use the default.
        """
        # Resolve voice: if it looks like a gender hint, map it
        groq_voice = self._resolve_voice(voice)

        # Try up to 3 keys before giving up
        max_retries = 3
        last_err: Optional[Exception] = None

        for attempt in range(max_retries):
            api_key = get_next_key("groq")
            if not api_key:
                logger.error("❌ No Groq API keys available for TTS")
                raise RuntimeError("No Groq API keys available")

            try:
                wav_bytes = await asyncio.to_thread(
                    self._call_api, api_key, text, groq_voice
                )
                logger.info(
                    f"🔊 Groq TTS: {len(wav_bytes)} bytes, "
                    f"voice={groq_voice}, attempt={attempt + 1}"
                )
                yield wav_bytes
                return

            except Exception as e:
                last_err = e
                if _is_quota_error(e):
                    logger.warning(
                        f"⚠️ Groq TTS key exhausted (attempt {attempt + 1}): {e}"
                    )
                    rotate_key("groq")
                    continue
                # Non-quota error — don't retry
                logger.error(f"❌ Groq TTS error: {e}")
                raise

        # All retries exhausted
        raise RuntimeError(f"Groq TTS failed after {max_retries} attempts: {last_err}")

    # ── private helpers ─────────────────────────────────────────────────

    @staticmethod
    def _call_api(api_key: str, text: str, voice: str) -> bytes:
        """Synchronous Groq TTS call (runs in thread)."""
        client = Groq(api_key=api_key)
        response = client.audio.speech.create(
            model=GROQ_TTS_MODEL,
            voice=voice,
            input=text,
            response_format=GROQ_TTS_FORMAT,
        )
        # response is an HttpxBinaryResponseContent — read into bytes
        buffer = io.BytesIO()
        for chunk in response.iter_bytes(chunk_size=8192):
            buffer.write(chunk)
        return buffer.getvalue()

    @staticmethod
    def _resolve_voice(voice_hint: str) -> str:
        """
        Map whatever voice string arrives to a valid Groq voice.

        Accepts:
            - Direct Groq names: "autumn", "daniel", etc.
            - Gender hints: "male", "female"
            - Anything else: falls back to default
        """
        hint = (voice_hint or "").strip().lower()

        # Direct match?
        if hint in {"autumn", "diana", "hannah", "austin", "daniel", "troy"}:
            return hint

        # Gender-based?
        if hint in GROQ_VOICE_MAP:
            return GROQ_VOICE_MAP[hint]

        # Default
        return GROQ_DEFAULT_VOICE
