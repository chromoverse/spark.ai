"""FakeEngines (TESTING.md §2): TTS engines with scripted latency, empty audio, and errors."""

from __future__ import annotations

from collections import deque
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

from tests.fakes.clock import FakeClock


class HttpError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status


@dataclass
class FakeTts:
    name: str
    clock: FakeClock
    latency_s: float = 0.1  # to the first chunk
    expressive: bool = False
    mime: str = "audio/mpeg"
    installed: bool = True
    # per-call behaviour, consumed in order; then "ok" forever: ok | empty | error503 | hang
    script: deque[str] = field(default_factory=deque)
    texts: list[str] = field(default_factory=list)  # what it was asked to say

    def available(self) -> bool:
        return self.installed

    async def synth(self, text: str, tone: str | None) -> AsyncGenerator[bytes, None]:
        self.texts.append(text)
        mode = self.script.popleft() if self.script else "ok"
        if mode == "error503":
            raise HttpError(503)
        if mode == "hang":
            await self.clock.sleep(3600)
        await self.clock.sleep(self.latency_s)
        if mode == "empty":
            return
        yield b"ID3fake-audio-1"
        yield b"fake-audio-2"
