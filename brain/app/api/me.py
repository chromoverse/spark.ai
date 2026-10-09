from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import Db, Me, Rt
from app.core.errors import BAD_INPUT, ApiError, ok
from app.db.audit import audit
from app.db.models import User, UserSettings
from app.gateway import push

router = APIRouter(prefix="/v2")

SETTINGS_FIELDS = (
    "language",
    "auto_detect_language",
    "voice",
    "verbosity",
    "address_as",
    "permission_mode",
    "allow_training_providers",
    "models",
)


def settings_dict(s: UserSettings) -> dict[str, Any]:
    return {f: getattr(s, f) for f in SETTINGS_FIELDS}


@router.get("/me")
async def me(me: Me, db: Db) -> dict[str, Any]:
    user = await db.scalar(select(User).where(User.id == me.user_id))
    s = await db.scalar(select(UserSettings).where(UserSettings.user_id == me.user_id))
    assert user is not None and s is not None  # session check guarantees the user exists
    return ok(
        {
            "user": {
                "id": str(user.id),
                "email": user.email,
                "name": user.name,
                "nickname": user.nickname,
                "plan": user.plan,
            },
            "device_id": str(me.device_id),
            "settings": settings_dict(s),
        }
    )


SUPPORTED_LANGUAGES = {"en"}
_NULLABLE = {"voice", "address_as"}


class SettingsPatch(BaseModel):
    """Send only what changes. `voice` and `address_as` can be cleared with null."""

    model_config = ConfigDict(extra="forbid")
    language: str | None = Field(default=None, pattern=r"^[a-z]{2}(-[A-Z]{2})?$")
    auto_detect_language: bool | None = None
    voice: str | None = Field(default=None, max_length=64)
    verbosity: Literal["brief", "normal", "detailed"] | None = None
    address_as: str | None = Field(default=None, max_length=40)
    permission_mode: Literal["default", "ask", "trust"] | None = None
    allow_training_providers: bool | None = None


@router.get("/settings")
async def get_settings(me: Me, db: Db) -> dict[str, Any]:
    s = await db.scalar(select(UserSettings).where(UserSettings.user_id == me.user_id))
    assert s is not None
    return ok(settings_dict(s))


@router.patch("/settings")
async def patch_settings(body: SettingsPatch, me: Me, rt: Rt, db: Db) -> dict[str, Any]:
    requested = body.model_dump(exclude_unset=True)
    if any(v is None and k not in _NULLABLE for k, v in requested.items()):
        raise ApiError("invalid_input", BAD_INPUT)
    if requested.get("language", "en") not in SUPPORTED_LANGUAGES:
        raise ApiError(
            "invalid_input", "English is all I speak for now. More languages are coming."
        )
    s = await db.scalar(
        select(UserSettings).where(UserSettings.user_id == me.user_id).with_for_update()
    )
    assert s is not None
    changed = {k: v for k, v in requested.items() if getattr(s, k) != v}
    event = None
    if changed:
        for k, v in changed.items():
            setattr(s, k, v)
        event = await push.record(rt, db, me.user_id, "settings.changed", {"changed": changed})
        audit(
            db,
            me.user_id,
            "settings_changed",
            actor=f"device:{me.device_id}",
            fields=sorted(changed),
        )
    await db.commit()
    if event is not None:
        await push.emit(rt, event)
    return ok(settings_dict(s))
