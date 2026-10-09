from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import TypeVar

T = TypeVar("T")


class Clock:
    """Injected everywhere time matters so tests can drive deadlines and cooldowns."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    def epoch_ms(self) -> int:
        return int(self.now().timestamp() * 1000)


async def within(clock: Clock, aw: Awaitable[T], seconds: float) -> T:
    """Awaits `aw` on the injected clock; TimeoutError (and `aw` cancelled) after `seconds`.
    asyncio.timeout can't be used: it runs on loop time, which tests can't move."""
    task = asyncio.ensure_future(aw)
    timer = asyncio.ensure_future(clock.sleep(seconds))
    try:
        await asyncio.wait({task, timer}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        timer.cancel()
        if not task.done():
            task.cancel()
            await asyncio.wait({task})
    if task.cancelled():
        raise TimeoutError
    return task.result()
