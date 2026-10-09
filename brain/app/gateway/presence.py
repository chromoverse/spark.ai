"""presence:{user} = hash device_id → last ping (epoch ms). Refreshed every 30 s while connected."""

from __future__ import annotations

import uuid
from typing import cast

from app.core.runtime import Runtime

TTL_S = 60
REFRESH_S = 30


def _key(user_id: uuid.UUID) -> str:
    return f"presence:{user_id}"


async def touch(rt: Runtime, user_id: uuid.UUID, device_id: uuid.UUID) -> None:
    async with rt.redis.pipeline(transaction=True) as pipe:
        pipe.hset(_key(user_id), str(device_id), rt.clock.epoch_ms())
        pipe.expire(_key(user_id), TTL_S)
        await pipe.execute()


async def drop(rt: Runtime, user_id: uuid.UUID, device_id: uuid.UUID) -> None:
    await rt.redis.hdel(_key(user_id), str(device_id))


async def online(rt: Runtime, user_id: uuid.UUID) -> set[str]:
    pings = cast(dict[str, str], await rt.redis.hgetall(_key(user_id)))  # decode_responses=True
    cutoff = rt.clock.epoch_ms() - TTL_S * 1000
    return {device for device, ts in pings.items() if int(ts) > cutoff}
