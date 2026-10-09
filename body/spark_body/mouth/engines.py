"""TTS engine contract and the engines themselves (REDESIGN §18). An engine streams encoded audio
chunks; the renderer plays them (Chromium decodes MP3/WAV, so the body needs no decoder)."""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator
from typing import Protocol

# PERSONA §5 tone → Groq Orpheus vocal direction. "chill" is the default voice: no tag.
ORPHEUS_DIRECTIONS = {
    "cheerful": "cheerful",
    "calm": "calm",
    "serious": "serious",
    "excited": "excited",
    "whisper": "whisper",
}
_TAGS = re.compile(r"\[[a-z_ ]{2,20}\]\s*", re.IGNORECASE)

STANDARD_SENTENCE = "Sure, I can help with that, it should only take a moment."  # 12 words


class TtsEngine(Protocol):
    name: str
    expressive: bool  # takes vocal-direction tags (Orpheus); others get them stripped
    mime: str

    def available(self) -> bool:
        """Dependencies installed and keys present. False → excluded before benchmarking."""
        ...

    def synth(self, text: str, tone: str | None) -> AsyncGenerator[bytes, None]:
        """`text` is already prepared (tone handled); yields encoded audio chunks."""
        ...


def prepare(engine: TtsEngine, text: str, tone: str | None) -> str:
    """FT5: tone tags become vocal directions on expressive engines and vanish elsewhere."""
    clean = _TAGS.sub("", text).strip()
    if engine.expressive and tone in ORPHEUS_DIRECTIONS:
        return f"[{ORPHEUS_DIRECTIONS[tone]}] {clean}"
    return clean


class EdgeTts:
    """Microsoft Edge read-aloud voices via `edge-tts` (free, natural, unofficial). Runs on the
    device because datacenter IPs get blocked (RESEARCH §5)."""

    name = "edge-tts"
    expressive = False
    mime = "audio/mpeg"

    def __init__(self, voice: str = "en-US-AvaMultilingualNeural") -> None:
        self.voice = voice

    def available(self) -> bool:
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            return False
        return True

    async def synth(self, text: str, tone: str | None) -> AsyncGenerator[bytes, None]:
        import edge_tts

        communicate = edge_tts.Communicate(text, self.voice)
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio" and chunk.get("data"):
                yield chunk["data"]
