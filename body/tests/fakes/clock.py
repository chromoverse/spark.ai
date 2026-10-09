from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import TypeVar

from spark_body.clock import Clock

T = TypeVar("T")


class FakeClock(Clock):
    """Time moves only on advance(); sleepers wake when their deadline passes."""

    def __init__(self) -> None:
        self._mono = 0.0
        self._sleepers: list[tuple[float, asyncio.Future[None]]] = []

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
        self._mono += seconds
        due = [s for s in self._sleepers if s[0] <= self._mono]
        self._sleepers = [s for s in self._sleepers if s[0] > self._mono]
        for _, fut in due:
            if not fut.done():
                fut.set_result(None)


async def drive(clock: FakeClock, aw: Awaitable[T], step: float = 0.01, limit_s: float = 60) -> T:
    """Awaits `aw` while simulated time moves `step` per event-loop pass. Body tests have no
    real I/O, so a few passes let every ready task run before time moves on."""
    task = asyncio.ensure_future(aw)
    for _ in range(int(limit_s / step)):
        for _ in range(10):
            await asyncio.sleep(0)
        if task.done():
            return task.result()
        clock.advance(step)
    task.cancel()
    raise AssertionError(f"still running after {limit_s}s of simulated time")
