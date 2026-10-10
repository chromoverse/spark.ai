from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select

from app.api.deps import Db, Me
from app.core.errors import BAD_INPUT, NOT_FOUND, ApiError, ok
from app.db.audit import audit
from app.db.models import Device, PermissionRule
from app.tools.registry import BY_NAME

router = APIRouter(prefix="/v2/permissions/rules")


class RuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str = Field(max_length=80)
    pattern: str = Field(default="", max_length=500)
    decision: Literal["deny", "ask", "allow"]
    device_id: uuid.UUID | None = None


def _rule(r: PermissionRule) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "tool": r.tool,
        "pattern": r.pattern,
        "decision": r.decision,
        "device_id": str(r.device_id) if r.device_id else None,
        "created_at": r.created_at.isoformat(),
    }


@router.get("")
async def list_rules(me: Me, db: Db) -> dict[str, Any]:
    rows = (
        await db.scalars(
            select(PermissionRule)
            .where(PermissionRule.user_id == me.user_id)
            .order_by(PermissionRule.created_at)
        )
    ).all()
    return ok({"items": [_rule(r) for r in rows], "next_cursor": None})


@router.post("")
async def add_rule(body: RuleIn, me: Me, db: Db) -> dict[str, Any]:
    """deny / ask / allow for a tool, optionally one device, with a glob on the input the tool
    matches (its path, command, or name). Precedence is deny → ask → allow (REDESIGN §7.2)."""
    if body.tool not in BY_NAME:
        raise ApiError("invalid_input", BAD_INPUT)
    if body.device_id is not None:
        owned = await db.scalar(
            select(Device.id).where(Device.id == body.device_id, Device.user_id == me.user_id)
        )
        if owned is None:
            raise ApiError("not_found", NOT_FOUND)
    rule = PermissionRule(
        user_id=me.user_id,
        tool=body.tool,
        pattern=body.pattern.replace("\\", "/"),
        decision=body.decision,
        device_id=body.device_id,
    )
    db.add(rule)
    await db.flush()
    audit(
        db, me.user_id, "permission_rule_added", actor=f"device:{me.device_id}", target=str(rule.id)
    )
    await db.commit()
    await db.refresh(rule)
    return ok(_rule(rule))


@router.delete("/{rule_id}")
async def delete_rule(rule_id: uuid.UUID, me: Me, db: Db) -> dict[str, Any]:
    gone = await db.execute(
        delete(PermissionRule)
        .where(PermissionRule.id == rule_id, PermissionRule.user_id == me.user_id)
        .returning(PermissionRule.id)
    )
    if gone.first() is None:
        raise ApiError("not_found", NOT_FOUND)
    audit(
        db,
        me.user_id,
        "permission_rule_removed",
        actor=f"device:{me.device_id}",
        target=str(rule_id),
    )
    await db.commit()
    return ok({"removed": True})
