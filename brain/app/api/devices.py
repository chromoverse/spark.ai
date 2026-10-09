from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select

from app.api.deps import Db, Me, Rt
from app.auth.sessions import revoke_device
from app.core.errors import NOT_FOUND, ApiError, ok
from app.db.audit import audit
from app.db.models import Device
from app.gateway import presence

router = APIRouter(prefix="/v2/devices")


class DevicePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=60)
    # "my phone" / "the laptop" resolve to the device marked default for that word (§26.3).
    is_default_for: list[Literal["phone", "laptop", "desktop", "tablet"]] | None = None


def _device(d: Device, me_device: uuid.UUID, online: set[str]) -> dict[str, Any]:
    return {
        "id": str(d.id),
        "name": d.name,
        "kind": d.kind,
        "platform": d.platform,
        "app_version": d.app_version,
        "parent_device_id": str(d.parent_device_id) if d.parent_device_id else None,
        "capabilities": d.capabilities,
        "engine_plan": d.engine_plan,
        "is_default_for": d.is_default_for,
        "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
        "online": str(d.id) in online,
        "current": d.id == me_device,
    }


async def _owned(db: Db, me: Me, device_id: uuid.UUID) -> Device:
    device = await db.scalar(
        select(Device).where(Device.id == device_id, Device.user_id == me.user_id)
    )
    if device is None:
        raise ApiError("not_found", NOT_FOUND)
    return device


@router.get("")
async def list_devices(me: Me, rt: Rt, db: Db) -> dict[str, Any]:
    devices = (
        await db.scalars(
            select(Device).where(Device.user_id == me.user_id).order_by(Device.created_at)
        )
    ).all()
    online = await presence.online(rt, me.user_id)
    return ok({"items": [_device(d, me.device_id, online) for d in devices], "next_cursor": None})


@router.patch("/{device_id}")
async def patch_device(
    device_id: uuid.UUID, body: DevicePatch, me: Me, rt: Rt, db: Db
) -> dict[str, Any]:
    device = await _owned(db, me, device_id)
    if body.name is not None:
        device.name = body.name
    if body.is_default_for is not None:
        claimed = set(body.is_default_for)
        others = await db.scalars(
            select(Device).where(Device.user_id == me.user_id, Device.id != device.id)
        )
        for other in others:
            if claimed & set(other.is_default_for):
                other.is_default_for = [w for w in other.is_default_for if w not in claimed]
        device.is_default_for = sorted(claimed)
    await db.commit()
    online = await presence.online(rt, me.user_id)
    return ok(_device(device, me.device_id, online))


@router.delete("/{device_id}")
async def delete_device(device_id: uuid.UUID, me: Me, rt: Rt, db: Db) -> dict[str, Any]:
    """Signs the device out and forgets it. Its socket drops on the next heartbeat (≤ 30 s)."""
    device = await _owned(db, me, device_id)
    await revoke_device(db, me.user_id, device.id, rt.clock.now())
    await db.execute(delete(Device).where(Device.id == device.id, Device.user_id == me.user_id))
    audit(db, me.user_id, "device_removed", actor=f"device:{me.device_id}", target=str(device.id))
    await db.commit()
    await presence.drop(rt, me.user_id, device.id)
    return ok({"removed": True})
