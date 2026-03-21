from __future__ import annotations

import asyncio
import fnmatch
import logging
import os
from typing import TYPE_CHECKING, Any, Optional, Union

import httpx
import redis.asyncio as redis
from upstash_redis.asyncio import Redis as UpstashRedis

from app.config import settings

if TYPE_CHECKING:
    from app.cache.lancedb_manager import LanceDBManager
    from app.cache.local_kv_manager import LocalKVManager

logger = logging.getLogger(__name__)


class BatchPipelineAdapter:
    """
    Backend-agnostic pipeline facade.

    Supports the subset used by cache mixins: `get`, `setex`, `execute`.
    """

    def __init__(self, manager: "BaseCacheManager") -> None:
        self.manager = manager
        self._commands: list[tuple[str, tuple[Any, ...]]] = []

    def get(self, key: str) -> "BatchPipelineAdapter":
        self._commands.append(("get", (key,)))
        return self

    def setex(self, key: str, seconds: int, value: str) -> "BatchPipelineAdapter":
        self._commands.append(("setex", (key, int(seconds), value)))
        return self

    async def execute(self) -> list[Any]:
        if not self._commands:
            return []

        get_indexes: list[int] = []
        get_keys: list[str] = []
        set_payloads: list[tuple[str, str, Optional[int]]] = []
        results: list[Any] = [None] * len(self._commands)

        for idx, (command, args) in enumerate(self._commands):
            if command == "get":
                get_indexes.append(idx)
                get_keys.append(str(args[0]))
            elif command == "setex":
                key, seconds, value = args
                set_payloads.append((str(key), str(value), int(seconds)))

        if get_keys:
            values = await self.manager.bulk_get(get_keys)
            for idx, value in zip(get_indexes, values):
                results[idx] = value

        if set_payloads:
            ok = await self.manager.bulk_set(set_payloads)
            set_result = bool(ok)
            cursor = 0
            for idx, (command, _) in enumerate(self._commands):
                if command == "setex":
                    results[idx] = set_result
                    cursor += 1

        return results


class BaseCacheManager:
    """Core cache connection manager (LocalKV, Redis, Upstash, Cloudflare KV)."""

    _instance: Optional["BaseCacheManager"] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if BaseCacheManager._initialized:
            return
        BaseCacheManager._initialized = True
        self.client: Union[redis.Redis, UpstashRedis, "LocalKVManager", None] = None
        self.vector_client: Optional["LanceDBManager"] = None
        self.cloud_sync_client: Optional[UpstashRedis] = None

        self._is_upstash = False
        self._is_desktop = False

        self._init_lock = asyncio.Lock()
        self._init_started = False

    async def _async_init(self):
        try:
            if settings.environment == "DESKTOP":
                await self._init_desktop()
                return
            if settings.environment == "PRODUCTION":
                await self._init_production()
                return
            await self._init_development()
        except Exception as e:
            self.client = None
            if settings.environment == "PRODUCTION":
                logger.warning(
                    "⚠️ Cache initialization failed in PRODUCTION; continuing in degraded mode: %s",
                    e,
                )
                return
            logger.error(f"❌ Initialization failed: {e}")
            raise

    async def _init_desktop(self) -> None:
        from app.cache.lancedb_manager import LanceDBManager
        from app.cache.local_kv_manager import LocalKVManager

        self.client = LocalKVManager()
        self.vector_client = LanceDBManager()
        self._is_desktop = True
        logger.info("🚀 Connected to LocalKV + LanceDB (Desktop)")

        # Optional desktop cloud sync channel (does not affect hot-path reads/writes).
        if bool(getattr(settings, "cache_sync_enabled", True)):
            self.cloud_sync_client = await self._create_upstash_client(optional=True)
            if self.cloud_sync_client is not None:
                logger.info("☁️ Desktop cloud sync channel ready (Upstash Redis)")

    async def _init_production(self) -> None:
        backend = str(getattr(settings, "cache_prod_backend", "upstash")).strip().lower()

        if backend == "upstash":
            await self._init_upstash_primary()
            return

        # Defensive fallback: local Redis for unknown backend values.
        logger.warning("Unknown production cache backend '%s', using local Redis fallback", backend)
        await self._init_development()

    async def _init_development(self) -> None:
        self.client = redis.Redis(
            host="localhost",
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        await self.client.ping()  # type: ignore[arg-type]
        logger.info("🐳 Connected to Local Redis (Dev)")

    async def _init_upstash_primary(self) -> None:
        upstash = await self._create_upstash_client(optional=False)
        self.client = upstash
        self._is_upstash = True
        logger.info("🌐 Connected to Upstash Redis (Production)")

    async def _create_upstash_client(self, *, optional: bool) -> Optional[UpstashRedis]:
        url = str(getattr(settings, "upstash_redis_rest_url", "")).strip()
        token = str(getattr(settings, "upstash_redis_rest_token", "")).strip()
        if not url or not token:
            if optional:
                return None
            raise RuntimeError("Missing Upstash configuration (UPSTASH_REDIS_REST_URL/TOKEN)")
        client = UpstashRedis(url=url, token=token)
        try:
            await client.ping()
        except Exception:
            if optional:
                return None
            raise
        return client



    async def _ensure_client(self):
        if self.client is not None:
            return
        async with self._init_lock:
            if self.client is not None:
                return
            if not self._init_started:
                self._init_started = True
                await self._async_init()

    def _safe_warn(self, msg: str):
        print(f"[Cache Warning] {msg}")

    def get_cloud_sync_client(self) -> Optional[UpstashRedis]:
        if self._is_upstash:
            return self.client  # type: ignore[return-value]
        return self.cloud_sync_client

    async def set(self, key: str, value: str, ex: Optional[int] = None) -> bool:
        try:
            await self._ensure_client()
            if self.client is None:
                return False

            await self.client.set(key, value, ex=ex)  # type: ignore[union-attr]
            return True
        except Exception as e:
            self._safe_warn(f"Failed to set key '{key}': {e}")
            return False

    async def get(self, key: str) -> Optional[str]:
        try:
            await self._ensure_client()
            if self.client is None:
                return None

            result = await self.client.get(key)  # type: ignore[union-attr]
            return str(result) if result is not None else None
        except Exception as e:
            self._safe_warn(f"Failed to get key '{key}': {e}")
            return None

    async def delete(self, *keys: str) -> bool:
        try:
            await self._ensure_client()
            if self.client is None:
                return False
            if not keys:
                return True

            await self.client.delete(*keys)  # type: ignore[union-attr]
            return True
        except Exception as e:
            self._safe_warn(f"Failed to delete keys: {e}")
            return False

    async def rpush(self, key: str, *values: str) -> bool:
        try:
            await self._ensure_client()
            if self.client is None:
                return False
            if not values:
                return True

            await self.client.rpush(key, *values)  # type: ignore[union-attr]
            return True
        except Exception as e:
            self._safe_warn(f"Failed to rpush to '{key}': {e}")
            return False

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        try:
            await self._ensure_client()
            if self.client is None:
                return []

            result = await self.client.lrange(key, start, end)  # type: ignore[union-attr]
            if result is None:
                return []
            if isinstance(result, list):
                return [str(item) if item is not None else "" for item in result]
            return []
        except Exception as e:
            self._safe_warn(f"Failed to lrange '{key}': {e}")
            return []

    async def scan(self, cursor: int = 0, match: Optional[str] = None, count: int = 100) -> tuple[int, list[str]]:
        try:
            await self._ensure_client()
            if self.client is None:
                return 0, []

            if self._is_upstash and isinstance(self.client, UpstashRedis):
                result = await self.client.scan(cursor, match=match, count=count)
                if isinstance(result, list) and len(result) == 2:
                    return int(result[0]) if result[0] else 0, result[1] if isinstance(result[1], list) else []
                return 0, []

            cursor_result, keys = await self.client.scan(cursor=cursor, match=match, count=count)  # type: ignore[union-attr]
            return int(cursor_result), [str(k) for k in keys] if keys else []
        except Exception as e:
            self._safe_warn(f"Failed to scan: {e}")
            return 0, []

    async def bulk_get(self, keys: list[str]) -> list[Optional[str]]:
        if not keys:
            return []
        await self._ensure_client()
        if self.client is None:
            return [None] * len(keys)

        if isinstance(self.client, redis.Redis):
            pipeline = self.client.pipeline()
            for key in keys:
                pipeline.get(key)
            values = await pipeline.execute()
            return [None if value is None else str(value) for value in values]

        values = await asyncio.gather(*(self.get(key) for key in keys), return_exceptions=True)
        normalized: list[Optional[str]] = []
        for value in values:
            if isinstance(value, BaseException) or value is None:
                normalized.append(None)
            else:
                normalized.append(str(value))
        return normalized

    async def bulk_set(self, items: list[tuple[str, str, Optional[int]]]) -> bool:
        if not items:
            return True
        await self._ensure_client()
        if self.client is None:
            return False

        if isinstance(self.client, redis.Redis):
            pipeline = self.client.pipeline()
            for key, value, ex in items:
                if ex is None:
                    pipeline.set(key, value)
                else:
                    pipeline.setex(key, int(ex), value)
            await pipeline.execute()
            return True

        for key, value, ex in items:
            ok = await self.set(key, value, ex=ex)
            if not ok:
                return False
        return True

    async def pipeline(self) -> Union[BatchPipelineAdapter, Any]:
        await self._ensure_client()
        if self.client is None:
            raise RuntimeError("Client not initialized")
        if isinstance(self.client, redis.Redis):
            return self.client.pipeline()
        return BatchPipelineAdapter(self)

    async def _delete_by_pattern(self, pattern: str) -> int:
        await self._ensure_client()
        if self.client is None:
            return 0

        redis_cursor = 0
        total_deleted = 0
        while True:
            redis_cursor, keys = await self.scan(cursor=redis_cursor, match=pattern, count=100)
            if keys:
                await self.delete(*keys)
                total_deleted += len(keys)
            if redis_cursor == 0:
                break
        return total_deleted
