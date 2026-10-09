from __future__ import annotations

from redis.asyncio import Redis

from app.core.errors import ApiError


async def hit(redis: Redis, scope: str, key: str, *, limit: int, window_s: int) -> None:
    """Count one request against `rl:{scope}:{key}`; raise `rate_limited` past the limit.
    ponytail: fixed window (allows a 2x burst at the edge); token bucket if that ever matters."""
    rkey = f"rl:{scope}:{key}"
    async with redis.pipeline(transaction=True) as pipe:
        pipe.incr(rkey)
        pipe.expire(rkey, window_s, nx=True)
        pipe.ttl(rkey)
        count, _, ttl = await pipe.execute()
    if count > limit:
        raise ApiError(
            "rate_limited",
            "Easy there. Give it a minute and try again.",
            retry_after_s=max(int(ttl), 1),
        )
