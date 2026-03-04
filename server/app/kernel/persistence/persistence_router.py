from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from typing import Any, Deque, Dict

from app.cache import cache_manager
from app.config import settings
from app.kernel.contracts.models import KernelEvent
from app.kernel.persistence.stats_store import get_kernel_stats_store

logger = logging.getLogger(__name__)


class KernelPersistenceRouter:
    """
    Environment-aware event persistence.

    Desktop:
    - Write event to in-memory cache immediately.
    - Batch flush to Mongo every 100 events or 5 seconds.

    Production:
    - Write-through to Mongo immediately.
    - Update cache for hot reads.
    """

    def __init__(self):
        self.environment = settings.environment
        self.stats_store = get_kernel_stats_store()

        self._cache_recent_events: Dict[str, Deque[dict[str, Any]]] = {}

        self._desktop_outbox: Deque[KernelEvent] = deque()
        self._flush_task: asyncio.Task | None = None
        self._running = False

        self._batch_size = 100
        self._flush_interval_s = 5
        self._cache_limit_per_user = 500

    async def start(self) -> None:
        if self._running:
            return
        self._running = True

        if self.environment == "desktop":
            self._flush_task = asyncio.create_task(self._desktop_flush_loop())
            logger.info("KernelPersistenceRouter started in desktop batch mode")
        else:
            logger.info("KernelPersistenceRouter started in production write-through mode")

    async def stop(self) -> None:
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None

        if self.environment == "desktop":
            await self._flush_desktop_outbox()

    async def write_event(self, event: KernelEvent) -> None:
        self._cache_event(event)

        if self.environment == "desktop":
            self._desktop_outbox.append(event)
            if len(self._desktop_outbox) >= self._batch_size:
                await self._flush_desktop_outbox()
            return

        await self.stats_store.persist_event(event)
        await self._update_hot_cache(event)

    def get_cached_user_events(self, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        queue = self._cache_recent_events.get(user_id)
        if not queue:
            return []
        return list(queue)[-max(1, min(limit, 500)) :]

    def cached_user_count(self) -> int:
        return len(self._cache_recent_events)

    def _cache_event(self, event: KernelEvent) -> None:
        queue = self._cache_recent_events.setdefault(event.user_id, deque(maxlen=self._cache_limit_per_user))
        queue.append(event.to_dict())

    async def _desktop_flush_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self._flush_interval_s)
            await self._flush_desktop_outbox()

    async def _flush_desktop_outbox(self) -> None:
        if not self._desktop_outbox:
            return

        batch: list[KernelEvent] = []
        while self._desktop_outbox and len(batch) < self._batch_size:
            batch.append(self._desktop_outbox.popleft())

        for event in batch:
            try:
                await self.stats_store.persist_event(event)
            except Exception as exc:
                logger.error("Desktop outbox persist failed, requeueing event: %s", exc)
                self._desktop_outbox.appendleft(event)
                break

    async def _update_hot_cache(self, event: KernelEvent) -> None:
        cache_key = f"kernel:recent:{event.user_id}"
        try:
            payload = json.dumps(event.to_dict())
            await cache_manager.rpush(cache_key, payload)
        except Exception as exc:
            logger.debug("Failed updating hot cache key=%s error=%s", cache_key, exc)


_persistence_router: KernelPersistenceRouter | None = None


def get_kernel_persistence_router() -> KernelPersistenceRouter:
    global _persistence_router
    if _persistence_router is None:
        _persistence_router = KernelPersistenceRouter()
    return _persistence_router


