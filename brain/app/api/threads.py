from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import Db, Me
from app.core.errors import NOT_FOUND, ApiError, ok
from app.db.models import Message, Thread

router = APIRouter(prefix="/v2/threads")


@router.get("")
async def list_threads(me: Me, db: Db, limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    rows = (
        await db.scalars(
            select(Thread)
            .where(Thread.user_id == me.user_id)
            .order_by(Thread.last_message_at.desc())
            .limit(limit)
        )
    ).all()
    items = [
        {"id": str(t.id), "title": t.title, "last_message_at": t.last_message_at.isoformat()}
        for t in rows
    ]
    return ok({"items": items, "next_cursor": None})


@router.get("/{thread_id}/messages")
async def list_messages(
    thread_id: uuid.UUID,
    me: Me,
    db: Db,
    limit: int = Query(50, ge=1, le=100),
    before: str | None = Query(None, max_length=40),
) -> dict[str, Any]:
    """Oldest first within the page; `before` = a message id for the page before it. Every
    device of the user sees the same thread (§26.4-G "continue on my phone")."""
    thread = await db.scalar(
        select(Thread.id).where(Thread.id == thread_id, Thread.user_id == me.user_id)
    )
    if thread is None:
        raise ApiError("not_found", NOT_FOUND)
    q = select(Message).where(Message.thread_id == thread_id, Message.user_id == me.user_id)
    if before:
        try:
            pivot = await db.get(Message, uuid.UUID(before))
        except ValueError:
            pivot = None
        if pivot is not None and pivot.user_id == me.user_id:
            q = q.where(Message.created_at < pivot.created_at)
    rows = (
        await db.scalars(q.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit))
    ).all()
    items = [
        {
            "id": str(m.id),
            "role": m.role,
            "content": m.content,
            "tier": m.tier,
            "device_id": str(m.device_id) if m.device_id else None,
            "created_at": m.created_at.isoformat(),
        }
        for m in reversed(rows)
    ]
    cursor = items[0]["id"] if len(rows) == limit else None
    return ok({"items": items, "next_cursor": cursor})
