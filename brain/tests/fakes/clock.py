from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from app.core.clock import Clock


class FakeClock(Clock):
    """Time only moves when a test calls advance(); sleepers wake when their deadline passes."""

    def __init__(self, start: datetime = datetime(2026, 10, 9, 9, 0, tzinfo=UTC)) -> None:
        self._now = start
        self._mono = 0.0
        self._sleepers: list[tuple[float, asyncio.Future[None]]] = []

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._mono

    async def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            await asyncio.sleep(0)
            return
        fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._sleepers.append((self._mono + seconds, fut))
        await fut

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)
        self._mono += seconds
        due = [s for s in self._sleepers if s[0] <= self._mono]
        self._sleepers = [s for s in self._sleepers if s[0] > self._mono]
        for _, fut in due:
            if not fut.done():
                fut.set_result(None)

    @property
    def sleepers(self) -> int:
        return sum(1 for _, f in self._sleepers if not f.done())
