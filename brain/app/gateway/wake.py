"""Wake-word arbitration (REDESIGN §26.2): when several devices hear "Hey Spark", the brain collects
claims for 150 ms and picks one: highest score + loudness, then the foreground device, then the one
used most recently. The winner gets `wake.grant`, the rest `wake.yield` (their next voice signal is
dropped). A device alone online is granted at once. Claims live in Redis so a window works across
brain processes."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, cast

from pydantic import Field

from app.core.runtime import Runtime
from app.core.security import Principal
from app.gateway import live, presence
from app.gateway.envelope import Envelope

logger = logging.getLogger(__name__)

WINDOW_S = 0.15
KEEP_S = 2  # claims and the window marker expire after this
YIELD_S = 3  # a yielded device's voice signals are dropped this long


class WakeClaim(Envelope):
    score: float = Field(ge=0, le=1)
    loudness: float = Field(ge=0, le=1)
    foreground: bool = False


def _rank(claim: dict[str, Any], used: dict[str, str]) -> tuple[float, bool, int]:
    return (
        round(claim["score"] + claim["loudness"], 3),
        bool(claim["foreground"]),
        int(used.get(claim["device"], 0)),
    )


async def claim(
    rt: Runtime, p: Principal, msg: WakeClaim, tasks: set[asyncio.Task[Any]]
) -> dict[str, Any]:
    claim_id = uuid.uuid4().hex
    online = await presence.online(rt, p.user_id)
    if online <= {str(p.device_id)}:
        return {"claim_id": claim_id, "decision": "grant"}
    entry = json.dumps(
        {
            "claim_id": claim_id,
            "device": str(p.device_id),
            "score": msg.score,
            "loudness": msg.loudness,
            "foreground": msg.foreground,
        }
    )
    claims, marker = f"wake:{p.user_id}:claims", f"wake:{p.user_id}:open"
    async with rt.redis.pipeline(transaction=True) as pipe:
        pipe.set(marker, claim_id, nx=True, ex=KEEP_S)
        pipe.rpush(claims, entry)
        pipe.expire(claims, KEEP_S)
        opened, _, _ = await pipe.execute()
    if opened:  # first claim of a window: this process decides it
        task = asyncio.create_task(_decide(rt, p.user_id))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
    return {"claim_id": claim_id, "decision": "pending"}


async def _decide(rt: Runtime, user_id: uuid.UUID) -> None:
    await rt.clock.sleep(WINDOW_S)
    claims, marker = f"wake:{user_id}:claims", f"wake:{user_id}:open"
    async with rt.redis.pipeline(transaction=True) as pipe:
        pipe.lrange(claims, 0, -1)
        pipe.delete(claims, marker)
        raw, _ = await pipe.execute()
    entries = [json.loads(r) for r in raw]
    if not entries:
        return
    used = cast(dict[str, str], await rt.redis.hgetall(f"wakeused:{user_id}"))
    winner = max(entries, key=lambda c: _rank(c, used))
    for c in entries:
        device = uuid.UUID(c["device"])
        if c is winner:
            await live.send(rt, device, "wake.grant", {"claim_id": c["claim_id"]})
            continue
        await rt.redis.set(f"yielded:{user_id}:{device}", 1, ex=YIELD_S)
        await live.send(
            rt, device, "wake.yield", {"claim_id": c["claim_id"], "winner": winner["device"]}
        )
    logger.info("wake arbitration", extra={"claims": len(entries)})
