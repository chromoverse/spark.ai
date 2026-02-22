"""
Groq STT Engine — Cloud-based Speech-to-Text via Groq API.

Uses ``whisper-large-v3-turbo`` for transcription.  Key rotation
follows the same ``_KeyCache`` / ``key_manager`` pattern as the
LLM and TTS providers.

Returns the same dict shape as ``WhisperService.transcribe()`` so
callers don't need to know which backend was used.
"""

import asyncio
import io
import logging
import time
from typing import Any, Dict, Optional

from groq import Groq  # type: ignore[import-untyped]
from app.ai.providers.key_manager import get_next_key, rotate_key

logger = logging.getLogger(__name__)

# ── Groq Whisper config ────────────────────────────────────────────────────
GROQ_STT_MODEL = "whisper-large-v3-turbo"
GROQ_STT_DEFAULT_LANG = "en"

# MIME → file-extension that Groq's file= param needs
_MIME_TO_EXT = {
    "audio/webm": ".webm",
    "audio/webm;codecs=opus": ".webm",
    "audio/wav": ".wav",
    "audio/mp3": ".mp3",
    "audio/mpeg": ".mp3",
    "audio/m4a": ".m4a",
    "audio/mp4": ".mp4",
    "audio/ogg": ".ogg",
}

# Errors that mean this key is done → rotate
_QUOTA_KEYWORDS = frozenset({
    "rate_limit", "resource_exhausted", "quota", "429",
    "insufficient_quota", "billing",
})


def _is_quota_error(err: Exception) -> bool:
    msg = str(err).lower()
    return any(kw in msg for kw in _QUOTA_KEYWORDS)


class GroqSTTEngine:
    """
    Groq cloud STT — drop-in replacement routing for local Whisper.

    ``transcribe()`` returns the same ``{success, text, ...}`` dict
    that ``WhisperService.transcribe()`` does, so the rest of the
    pipeline (session manager, socket handlers) doesn't change.
    """

    async def transcribe(
        self,
        audio_data: Any,
        mime_type: str = "audio/webm",
        language: Optional[str] = GROQ_STT_DEFAULT_LANG,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Transcribe audio via Groq Whisper.

        Args:
            audio_data: raw bytes (or base64 str — decoded first)
            mime_type:  MIME type of the audio
            language:   ISO language code

        Returns:
            Dict compatible with WhisperService output.
        """
        start = time.time()

        # ── Decode ──
        if isinstance(audio_data, str):
            import base64
            audio_bytes = base64.b64decode(audio_data)
        else:
            audio_bytes = bytes(audio_data)

        if len(audio_bytes) < 1000:
            return {
                "success": False,
                "text": "",
                "message": "Audio data too small (< 1 KB)",
            }

        ext = _MIME_TO_EXT.get(mime_type.split(";")[0].strip(), ".webm")

        # ── Try up to 3 keys ──
        max_retries = 3
        last_err: Optional[Exception] = None

        for attempt in range(max_retries):
            api_key = get_next_key("groq")
            if not api_key:
                return {
                    "success": False,
                    "text": "",
                    "error": "No Groq API keys available",
                }

            try:
                text = await asyncio.to_thread(
                    self._call_api, api_key, audio_bytes, ext, language or GROQ_STT_DEFAULT_LANG
                )
                elapsed = time.time() - start

                text = (text or "").strip()
                if not text or len(text) < 2:
                    return {
                        "success": False,
                        "text": "",
                        "message": "No speech detected",
                        "duration": round(elapsed, 2),
                    }

                logger.info(f"✅ Groq STT: '{text}' ({elapsed:.2f}s)")
                return {
                    "success": True,
                    "text": text,
                    "processing_time": round(elapsed, 2),
                }

            except Exception as e:
                last_err = e
                if _is_quota_error(e):
                    logger.warning(
                        f"⚠️ Groq STT key exhausted (attempt {attempt + 1}): {e}"
                    )
                    rotate_key("groq")
                    continue
                logger.error(f"❌ Groq STT error: {e}")
                return {
                    "success": False,
                    "text": "",
                    "error": str(e),
                }

        return {
            "success": False,
            "text": "",
            "error": f"Groq STT failed after {max_retries} attempts: {last_err}",
        }

    async def transcribe_simple(
        self,
        audio_data: Any,
        mime_type: str = "audio/webm",
        **kwargs,
    ) -> str:
        """Return just the text string (backward-compatible helper)."""
        result = await self.transcribe(audio_data, mime_type, **kwargs)
        return result.get("text", "")

    # ── private ─────────────────────────────────────────────────────────

    @staticmethod
    def _call_api(
        api_key: str,
        audio_bytes: bytes,
        ext: str,
        language: str,
    ) -> str:
        """Synchronous Groq STT call (runs in thread)."""
        client = Groq(api_key=api_key)
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = f"audio{ext}"  # Groq needs a filename hint

        response = client.audio.transcriptions.create(
            model=GROQ_STT_MODEL,
            file=audio_file,
            language=language,
            response_format="text",
        )
        return str(response).strip()


# ── Module-level singleton ─────────────────────────────────────────────────
groq_stt_engine = GroqSTTEngine()
