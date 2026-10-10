from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import Db, Me
from app.core.errors import ok
from app.db.models import UserSettings
from app.tools import permissions
from app.tools.registry import ALL

router = APIRouter(prefix="/v2/capabilities")


@router.get("/tools")
async def list_tools(me: Me, db: Db) -> dict[str, Any]:
    """The catalog with each tool's risk and what happens by default under the user's mode and
    rules (Capabilities page, REDESIGN §24). Pattern rules can still change single calls."""
    mode = await db.scalar(
        select(UserSettings.permission_mode).where(UserSettings.user_id == me.user_id)
    )
    rules = await permissions.load_db(db, me.user_id)
    hidden = permissions.hidden(rules)
    items = []
    for t in ALL:
        bare = [r for r in rules if r.tool == t.name and not r.pattern and r.device_id is None]
        verdict = (
            "deny"
            if t.name in hidden
            else permissions.decide(t, {}, mode=mode or "default", rules=bare)
        )
        items.append(
            {
                "name": t.name,
                "description": t.description,
                "target": t.target,
                "risk": t.risk.value,
                "requires": sorted(t.requires),
                "permission": verdict,
            }
        )
    return ok({"items": items, "next_cursor": None})
