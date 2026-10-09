"""TTS engine contract and the engines themselves (REDESIGN §18). An engine streams encoded audio
chunks; the renderer plays them (Chromium decodes MP3/WAV, so the body needs no decoder)."""

from __future__ import annotations

import asyncio
import json
import re
import urllib.error
import urllib.request
from collections.abc import AsyncGenerator
from dataclasses import dataclass
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


@dataclass
class BrainLink:
    """Where the brain is and a current access token. Electron main sets it (`auth.set`) and
    refreshes it before it expires; it lives only in memory."""

    url: str = ""
    token: str = ""


class ProxyError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"brain proxy {status}")
        self.status = status


class OrpheusProxy:
    """Groq Orpheus through the brain's proxy (platform keys stay in the brain): the most
    expressive voice, ~100 free clips a day, so it leads the plan while it fits and has quota."""

    name = "groq-orpheus"
    expressive = True
    mime = "audio/wav"

    def __init__(self, link: BrainLink, voice: str = "daniel") -> None:
        self.link = link
        self.voice = voice

    def available(self) -> bool:
        return bool(self.link.url and self.link.token)

    def _post(self, text: str) -> bytes:
        req = urllib.request.Request(  # noqa: S310 (the brain URL from Electron main)
            f"{self.link.url}/v2/proxy/tts",
            data=json.dumps({"text": text[:200], "voice": self.voice}).encode(),
            headers={
                "Authorization": f"Bearer {self.link.token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as r:  # noqa: S310
                data: bytes = r.read()
                return data
        except urllib.error.HTTPError as exc:
            raise ProxyError(exc.code) from None

    async def synth(self, text: str, tone: str | None) -> AsyncGenerator[bytes, None]:
        # `text` already carries the vocal direction (prepare); the proxy gets no extra tone
        yield await asyncio.to_thread(self._post, text)
