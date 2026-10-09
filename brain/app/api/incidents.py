from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import Db, Me
from app.core.errors import ok
from app.db.models import Incident

router = APIRouter(prefix="/v2/incidents")


@router.get("")
async def list_incidents(me: Me, db: Db, limit: int = Query(50, ge=1, le=100)) -> dict[str, Any]:
    """Newest first. The Engines and Activity pages show these (REDESIGN §19.3)."""
    rows = (
        await db.scalars(
            select(Incident)
            .where(Incident.user_id == me.user_id)
            .order_by(Incident.ts.desc())
            .limit(limit)
        )
    ).all()
    items = [
        {
            "id": str(i.id),
            "device_id": str(i.device_id) if i.device_id else None,
            "stage": i.stage,
            "engine_or_provider": i.engine_or_provider,
            "error": i.error,
            "remedy": i.remedy,
            "outcome": i.outcome,
            "signal_id": i.signal_id,
            "ts": i.ts.isoformat(),
        }
        for i in rows
    ]
    return ok({"items": items, "next_cursor": None})
