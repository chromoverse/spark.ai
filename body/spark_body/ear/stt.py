"""STT engine contract (REDESIGN §18): on-device model first, Groq Whisper through the brain's
proxy as the cloud fallback. Engines land with their fitness probes; the plan stays empty until
one passes on this device."""

from __future__ import annotations

import asyncio
import io
import json
import urllib.error
import urllib.request
import wave
from dataclasses import dataclass
from typing import Protocol

from spark_body.mouth.engines import BrainLink, ProxyError


@dataclass(frozen=True)
class Transcript:
    text: str
    lang: str = "en"
    confidence: float | None = None


class SttEngine(Protocol):
    name: str
    on_device: bool  # False → audio leaves the device (RULES §9: only when the plan picks it)

    def available(self) -> bool: ...

    async def transcribe(self, pcm16: bytes, sample_rate: int) -> Transcript: ...


def wav(pcm16: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm16)
    return buf.getvalue()


class WhisperProxy:
    """Groq Whisper through the brain's proxy: the cloud fallback (§18). Audio leaves the
    device only when this engine is first in the plan (RULES §9)."""

    name = "groq-whisper"
    on_device = False

    def __init__(self, link: BrainLink, lang: str = "en") -> None:
        self.link = link
        self.lang = lang

    def available(self) -> bool:
        return bool(self.link.url and self.link.token)

    def _post(self, clip: bytes) -> dict[str, object]:
        req = urllib.request.Request(  # noqa: S310 (the brain URL from Electron main)
            f"{self.link.url}/v2/proxy/stt?lang={self.lang}",
            data=clip,
            headers={"Authorization": f"Bearer {self.link.token}", "Content-Type": "audio/wav"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310
                body: dict[str, object] = json.loads(r.read())
                return body
        except urllib.error.HTTPError as exc:
            raise ProxyError(exc.code) from None

    async def transcribe(self, pcm16: bytes, sample_rate: int) -> Transcript:
        body = await asyncio.to_thread(self._post, wav(pcm16, sample_rate))
        data = body.get("data")
        text = str(data.get("text", "")) if isinstance(data, dict) else ""
        return Transcript(text.strip(), self.lang)
