from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime


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
