"""STT engine contract (REDESIGN §18): on-device model first, Groq Whisper through the brain's
proxy as the cloud fallback. Engines land with their fitness probes; the plan stays empty until
one passes on this device."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


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
