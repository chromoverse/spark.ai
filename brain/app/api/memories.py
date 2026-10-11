from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import Db, Me, Rt
from app.core.errors import NOT_FOUND, ApiError, ok
from app.db.audit import audit
from app.db.models import Memory
from app.memory import store

router = APIRouter(prefix="/v2/memories")


class MemoryPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str | None = Field(default=None, min_length=1, max_length=500)
    kind: Literal["preference", "person", "routine", "fact", "correction"] | None = None
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    confirmed: Literal[True] | None = None  # the user's OK; to drop one, delete it


def _memory(m: Memory) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "kind": m.kind,
        "text": m.text,
        "importance": round(m.importance, 2),
        "confirmed": m.confirmed,
        "last_used_at": m.last_used_at.isoformat() if m.last_used_at else None,
        "expires_at": m.expires_at.isoformat() if m.expires_at else None,
        "created_at": m.created_at.isoformat(),
        "updated_at": m.updated_at.isoformat(),
    }


@router.get("")
async def list_memories(
    me: Me,
    rt: Rt,
    db: Db,
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, Any]:
    """Everything Spark remembers, newest first (unconfirmed ones included, for the user to OK);
    `q` searches by meaning and words instead."""
    if q.strip():
        found = await store.search(rt, me.user_id, q, limit, confirmed_only=False, touch=False)
        ids = [f.id for f in found]
        rows = {
            m.id: m
            for m in await db.scalars(
                select(Memory).where(Memory.user_id == me.user_id, Memory.id.in_(ids))
            )
        }
        items = [_memory(rows[i]) for i in ids if i in rows]
    else:
        rows_ = await db.scalars(
            select(Memory)
            .where(Memory.user_id == me.user_id)
            .order_by(Memory.created_at.desc())
            .limit(limit)
        )
        items = [_memory(m) for m in rows_]
    return ok({"items": items, "next_cursor": None})


@router.patch("/{memory_id}")
async def edit_memory(memory_id: uuid.UUID, body: MemoryPatch, me: Me, rt: Rt, db: Db) -> Any:
    changes = body.model_dump(exclude_none=True)
    row = (
        await store.edit(rt, me.user_id, memory_id, changes)
        if changes
        else await db.scalar(
            select(Memory).where(Memory.id == memory_id, Memory.user_id == me.user_id)
        )
    )
    if row is None:
        raise ApiError("not_found", NOT_FOUND)
    audit(
        db,
        me.user_id,
        "memory_edited",
        actor=f"device:{me.device_id}",
        target=str(memory_id),
        fields=sorted(changes),
    )
    await db.commit()
    return ok(_memory(row))


@router.delete("/{memory_id}")
async def forget_memory(memory_id: uuid.UUID, me: Me, rt: Rt, db: Db) -> dict[str, Any]:
    """Forget: the row and its embedding are deleted, and the cached profile with them."""
    if not await store.delete_one(rt, me.user_id, memory_id):
        raise ApiError("not_found", NOT_FOUND)
    audit(db, me.user_id, "memory_forgotten", actor=f"device:{me.device_id}", target=str(memory_id))
    await db.commit()
    return ok({"removed": True})
