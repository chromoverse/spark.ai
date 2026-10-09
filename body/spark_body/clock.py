from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable
from typing import TypeVar

T = TypeVar("T")


class Clock:
    """Injected wherever latency is measured or a deadline applies, so tests can drive time."""

    def monotonic(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


async def within(clock: Clock, aw: Awaitable[T], seconds: float) -> T:
    """Awaits `aw` on the injected clock; TimeoutError (and `aw` cancelled) after `seconds`."""
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
