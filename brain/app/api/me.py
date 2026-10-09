from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import Db, Me
from app.core.errors import ok
from app.db.models import User, UserSettings

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
