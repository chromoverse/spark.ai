"""Live brain → device events (reply.delta, reply.cue, tool.call, tool.cancel). They go to one
device, aren't written to the sync log, and their id is random: the thread history keeps the
result, so a device that missed them catches up from messages, not replays (API.md §3)."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from app.core.logging import trace_id_var
from app.core.runtime import Runtime
from app.gateway.push import NAMESPACE

logger = logging.getLogger(__name__)


def device_room(device_id: uuid.UUID) -> str:
    return f"device:{device_id}"


async def send(rt: Runtime, device_id: uuid.UUID, event: str, payload: dict[str, Any]) -> None:
    envelope = {
        "v": 2,
        "id": uuid.uuid4().hex,
        "ts": rt.clock.epoch_ms(),
        "trace_id": trace_id_var.get(),
        **payload,
    }
    try:
        async with asyncio.timeout(2):
            await rt.sio.emit(event, envelope, room=device_room(device_id), namespace=NAMESPACE)
    except Exception:
        logger.warning("live emit failed", extra={"event": event})
