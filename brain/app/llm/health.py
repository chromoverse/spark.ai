"""Per provider/key/model health in Redis (`health:{provider}:{key}:{model}`, REDESIGN §5.5, §19):
circuit state, consecutive failures, and a TTFT moving average. The key part is a hash prefix of
the API key, never the key."""

from __future__ import annotations

import hashlib
from typing import cast

from redis.asyncio import Redis

from app.core.clock import Clock
from app.llm.types import ProviderError

EWMA = 0.2
TTL_S = 24 * 3600
STRIKES = 2  # consecutive outages/timeouts before the circuit opens
COOLDOWN_S = {"rate_limited": 60.0, "rejected": 300.0, "outage": 30.0}


def health_id(provider: str, api_key: str, model: str) -> str:
    return f"{provider}:{hashlib.sha256(api_key.encode()).hexdigest()[:8]}:{model}"


class Health:
    def __init__(self, redis: Redis, clock: Clock) -> None:
        self.redis = redis
        self.clock = clock

    @staticmethod
    def _key(hid: str) -> str:
        return f"health:{hid}"

    async def closed(self, hids: list[str]) -> list[bool]:
        """True where the circuit is closed (the entry may be tried)."""
        if not hids:
            return []
        async with self.redis.pipeline(transaction=False) as pipe:
            for hid in hids:
                pipe.hget(self._key(hid), "open_until")
            values = cast(list[str | None], await pipe.execute())
        now = self.clock.now().timestamp()
        return [v is None or float(v) <= now for v in values]

    async def ok(self, hid: str, ttft_ms: float) -> None:
        key = self._key(hid)
        prev = await self.redis.hget(key, "ttft_ms")
        ewma = ttft_ms if prev is None else (1 - EWMA) * float(prev) + EWMA * ttft_ms
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.hset(key, mapping={"ttft_ms": round(ewma, 1), "fails": 0})
            pipe.hdel(key, "open_until")
            pipe.expire(key, TTL_S)
            await pipe.execute()

    async def fail(self, hid: str, err: ProviderError) -> None:
        key = self._key(hid)
        now = self.clock.now().timestamp()
        fails = int(await self.redis.hincrby(key, "fails", 1))
        if err.kind == "rate_limited":
            cooldown: float | None = err.retry_after_s or COOLDOWN_S["rate_limited"]
        elif err.kind == "rejected":
            cooldown = COOLDOWN_S["rejected"]
        elif err.kind == "malformed":
            cooldown = None  # a quality miss, not an outage: the chain falls through per call
        else:
            cooldown = COOLDOWN_S["outage"] if fails >= STRIKES else None
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.hset(key, "last_error", err.kind)
            if cooldown is not None:
                pipe.hset(key, "open_until", now + cooldown)
            pipe.expire(key, TTL_S)
            await pipe.execute()

    async def snapshot(self, hid: str) -> dict[str, str]:
        return cast(dict[str, str], await self.redis.hgetall(self._key(hid)))
