from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from app.kernel.contracts.models import KernelEvent

logger = logging.getLogger(__name__)


Subscriber = Callable[[KernelEvent], Awaitable[None] | None]


class KernelEventBus:
    def __init__(self):
        self._subscribers: list[Subscriber] = []

    def subscribe(self, subscriber: Subscriber) -> None:
        self._subscribers.append(subscriber)

    async def emit(self, event: KernelEvent) -> None:
        for subscriber in self._subscribers:
            try:
                result = subscriber(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.error("Kernel event subscriber failed: %s", exc)


_event_bus: KernelEventBus | None = None


def get_kernel_event_bus() -> KernelEventBus:
    global _event_bus
    if _event_bus is None:
        _event_bus = KernelEventBus()
    return _event_bus


async def emit_kernel_event(event: KernelEvent) -> None:
    await get_kernel_event_bus().emit(event)


