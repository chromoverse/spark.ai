from __future__ import annotations

import logging

from app.kernel.eventing.event_bus import get_kernel_event_bus
from app.kernel.observability.log_index import get_kernel_log_index
from app.kernel.persistence.persistence_router import get_kernel_persistence_router

logger = logging.getLogger(__name__)


class KernelRuntime:
    def __init__(self):
        self.event_bus = get_kernel_event_bus()
        self.log_index = get_kernel_log_index()
        self.persistence_router = get_kernel_persistence_router()
        self._initialized = False

    async def start(self) -> None:
        if self._initialized:
            return

        self.event_bus.subscribe(self.persistence_router.write_event)
        self.event_bus.subscribe(self.log_index.record_event)
        await self.persistence_router.start()

        self._initialized = True
        logger.info("Kernel runtime initialized")

    async def stop(self) -> None:
        await self.persistence_router.stop()


_runtime: KernelRuntime | None = None


def get_kernel_runtime() -> KernelRuntime:
    global _runtime
    if _runtime is None:
        _runtime = KernelRuntime()
    return _runtime


async def init_kernel_runtime() -> KernelRuntime:
    runtime = get_kernel_runtime()
    await runtime.start()
    return runtime


