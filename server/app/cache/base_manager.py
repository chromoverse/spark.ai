
import redis.asyncio as redis
from upstash_redis.asyncio import Redis as UpstashRedis
import logging
import asyncio
from typing import Any, Optional, List, Union, Protocol
from app.config import settings

logger = logging.getLogger(__name__)

class RedisPipeline(Protocol):
    """Protocol for Redis pipeline operations"""
    def get(self, key: str) -> Any: ...
    def setex(self, key: str, seconds: int, value: str) -> Any: ...
    async def execute(self) -> List[Any]: ...

class UpstashMockPipeline:
    """Mock pipeline for Upstash (executes commands immediately)"""
    def __init__(self, client: Any):
        self.client = client
        self.commands: List[tuple] = []
    
    def get(self, key: str) -> 'UpstashMockPipeline':
        self.commands.append(('get', key))
        return self
    
    def setex(self, key: str, seconds: int, value: str) -> 'UpstashMockPipeline':
        self.commands.append(('setex', key, seconds, value))
        return self
    
    async def execute(self) -> List[Any]:
        results = []
        for cmd in self.commands:
            if cmd[0] == 'get':
                result = await self.client.get(cmd[1])
                results.append(result)
            elif cmd[0] == 'setex':
                await self.client.setex(cmd[1], cmd[2], cmd[3])
                results.append(True)
        return results

class BaseRedisManager:
    """Core Redis connection and basic operations"""
    _instance: Optional['BaseRedisManager'] = None
    _initialized: bool = False
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.client: Union[redis.Redis, UpstashRedis, None] = None # type: ignore
        self._is_upstash = False
        self._init_lock = asyncio.Lock()
        self._init_started = False

    async def _async_init(self):
        try:
            if settings.environment == "production":
                self.client = UpstashRedis(
                    url=settings.upstash_redis_rest_url,
                    token=settings.upstash_redis_rest_token,
                )
                self._is_upstash = True
                await self.client.ping() # type: ignore
                logger.info("🌐 Connected to Upstash Redis")
            else:
                self.client = redis.Redis(
                    host='localhost',
                    port=6379,
                    db=0,
                    decode_responses=True,
                    socket_connect_timeout=3,
                    socket_timeout=3
                )
                self._is_upstash = False
                await self.client.ping() # type: ignore
                logger.info("🐳 Connected to Local Docker Redis")
        except Exception as e:
            logger.error(f"❌ Redis initialization failed: {e}")
            self.client = None
            raise

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
        print(f"[Redis Warning] {msg}")

    async def set(self, key: str, value: str, ex: Optional[int] = None) -> bool:
        try:
            await self._ensure_client()
            await self.client.set(key, value, ex=ex) # type: ignore
            return True
        except Exception as e:
            self._safe_warn(f"Failed to set key '{key}': {e}")
            return False

    async def get(self, key: str) -> Optional[str]:
        try:
            await self._ensure_client()
            return await self.client.get(key) # type: ignore
        except Exception as e:
            self._safe_warn(f"Failed to get key '{key}': {e}")
            return None

    async def delete(self, *keys: str) -> bool:
        try:
            await self._ensure_client()
            await self.client.delete(*keys) # type: ignore
            return True
        except Exception as e:
            self._safe_warn(f"Failed to delete keys: {e}")
            return False

    async def rpush(self, key: str, *values: str) -> bool:
        try:
            await self._ensure_client()
            await self.client.rpush(key, *values) # type: ignore
            return True
        except Exception as e:
            self._safe_warn(f"Failed to rpush to '{key}': {e}")
            return False

    async def lrange(self, key: str, start: int, end: int) -> List[str]:
        try:
            await self._ensure_client()
            result = await self.client.lrange(key, start, end) # type: ignore
            if result is None: return []
            if isinstance(result, list):
                return [str(item) if item else "" for item in result]
            return []
        except Exception as e:
            self._safe_warn(f"Failed to lrange '{key}': {e}")
            return []

    async def scan(self, cursor: int = 0, match: Optional[str] = None, count: int = 100) -> tuple[int, List[str]]:
        try:
            await self._ensure_client()
            if self._is_upstash:
                result = await self.client.scan(cursor, match=match, count=count) # type: ignore
                if isinstance(result, list) and len(result) == 2:
                    return int(result[0]) if result[0] else 0, result[1] if isinstance(result[1], list) else []
                return 0, []
            else:
                cursor_result, keys = await self.client.scan(cursor=cursor, match=match, count=count) # type: ignore
                return int(cursor_result), list(keys) if keys else []
        except Exception as e:
            self._safe_warn(f"Failed to scan: {e}")
            return 0, []

    async def pipeline(self) -> RedisPipeline:
        await self._ensure_client()
        if self._is_upstash:
            return UpstashMockPipeline(self.client) # type: ignore
        return self.client.pipeline() # type: ignore

    async def _delete_by_pattern(self, pattern: str) -> int:
        cursor = 0
        total_deleted = 0
        while True:
            cursor, keys = await self.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                await self.delete(*keys)
                total_deleted += len(keys)
            if cursor == 0: break
        return total_deleted
