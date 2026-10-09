"""Brain → device events. Each one is written to the `events` sync log first (its seq becomes the
envelope `id`), then emitted to every online device of the user after the caller commits."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import trace_id_var
from app.core.runtime import Runtime
from app.db.models import Event

logger = logging.getLogger(__name__)

NAMESPACE = "/v2"


def user_room(user_id: uuid.UUID) -> str:
    return f"user:{user_id}"


async def record(
    rt: Runtime, db: AsyncSession, user_id: uuid.UUID, type_: str, payload: dict[str, Any]
) -> Event:
    event = Event(user_id=user_id, type=type_, payload=payload, ts=rt.clock.now())
    db.add(event)
    await db.flush()
    return event


async def emit(rt: Runtime, event: Event) -> None:
    """Best effort: a device that misses it catches up from the log via sync.resume (X4)."""
    envelope = {
        "v": 2,
        "id": str(event.seq),
        "ts": int(event.ts.timestamp() * 1000),
        "trace_id": trace_id_var.get(),
        **event.payload,
    }
    try:
        async with asyncio.timeout(2):
            await rt.sio.emit(
                event.type, envelope, room=user_room(event.user_id), namespace=NAMESPACE
            )
    except Exception:
        logger.warning("event emit failed", extra={"event": event.type, "seq": event.seq})
