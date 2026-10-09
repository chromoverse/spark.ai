"""Users, devices, and per-device sessions with rotating refresh tokens.

Refresh token = "<session_id>.<secret>". Only sha256(secret) is stored. Every refresh swaps the
secret; presenting an old secret for a live session means the token leaked, so the whole
session is revoked (X3). Clients must refresh one at a time.
"""

from __future__ import annotations

import hmac
import logging
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import SIGN_IN_AGAIN, ApiError
from app.core.runtime import Runtime
from app.core.security import ACCESS_TTL_S, Principal, issue_access, sha256_hex
from app.db.audit import audit
from app.db.base import uuid7
from app.db.models import AuthIdentity, Device, Session, User, UserSettings

logger = logging.getLogger(__name__)

REFRESH_TTL = timedelta(days=60)


class DeviceIn(BaseModel):
    """The device signing in. Passing a known `id` keeps the same device (only if it's yours)."""

    model_config = ConfigDict(extra="forbid")
    id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=60)
    kind: Literal["desktop", "mobile"] = "desktop"
    platform: str | None = Field(default=None, max_length=40)
    app_version: str | None = Field(default=None, max_length=40)


async def find_or_create_user(
    db: AsyncSession, *, email: str, provider: str, subject: str, name: str | None = None
) -> User:
    """Identity first, then a verified email match (links Google to an OTP account), then new."""
    user = await db.scalar(
        select(User)
        .join(AuthIdentity, AuthIdentity.user_id == User.id)
        .where(AuthIdentity.provider == provider, AuthIdentity.subject == subject)
    )
    if user is None:
        user = await db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, name=name)
            db.add(user)
            await db.flush()
            db.add(UserSettings(user_id=user.id))
        db.add(AuthIdentity(user_id=user.id, provider=provider, subject=subject))
    if name and not user.name:
        user.name = name
    return user


async def sign_in(
    rt: Runtime, db: AsyncSession, user: User, device_in: DeviceIn, *, method: str
) -> dict[str, Any]:
    """Registers (or reuses) the device, opens a fresh session, commits, and returns tokens."""
    now = rt.clock.now()
    device = None
    if device_in.id is not None:
        device = await db.scalar(
            select(Device).where(Device.id == device_in.id, Device.user_id == user.id)
        )
    if device is None:
        device = Device(user_id=user.id, kind=device_in.kind, name=device_in.name)
        db.add(device)
    else:
        await revoke_device(db, user.id, device.id, now)
    device.name = device_in.name
    device.platform = device_in.platform
    device.app_version = device_in.app_version
    device.last_seen_at = now
    await db.flush()

    session_id = uuid7()
    secret = secrets.token_urlsafe(32)
    db.add(
        Session(
            id=session_id,
            user_id=user.id,
            device_id=device.id,
            refresh_hash=sha256_hex(secret),
            expires_at=now + REFRESH_TTL,
            last_used_at=now,
        )
    )
    audit(db, user.id, "sign_in", target=f"device:{device.id}", method=method)
    await db.commit()
    logger.info("signed in", extra={"method": method, "device": str(device.id)})
    principal = Principal(user.id, device.id, session_id)
    return _tokens(rt, principal, f"{session_id}.{secret}") | {
        "user": {"id": str(user.id), "email": user.email, "name": user.name},
    }


async def rotate(rt: Runtime, db: AsyncSession, refresh_token: str) -> dict[str, Any]:
    sid_str, _, secret = refresh_token.partition(".")
    try:
        sid = uuid.UUID(sid_str)
    except ValueError:
        raise ApiError("unauthorized", SIGN_IN_AGAIN) from None
    now = rt.clock.now()
    session = await db.scalar(select(Session).where(Session.id == sid).with_for_update())
    if session is None or session.revoked_at is not None or session.expires_at <= now:
        raise ApiError("unauthorized", SIGN_IN_AGAIN)
    if not hmac.compare_digest(sha256_hex(secret), session.refresh_hash):
        session.revoked_at = now
        audit(db, session.user_id, "refresh_reuse", actor="system", target=f"session:{sid}")
        await db.commit()
        logger.warning("refresh token reuse; session revoked", extra={"session": str(sid)})
        raise ApiError("unauthorized", SIGN_IN_AGAIN)
    new_secret = secrets.token_urlsafe(32)
    session.refresh_hash = sha256_hex(new_secret)
    session.last_used_at = now
    session.expires_at = now + REFRESH_TTL
    await db.commit()
    principal = Principal(session.user_id, session.device_id, session.id)
    return _tokens(rt, principal, f"{sid}.{new_secret}")


async def check_session(rt: Runtime, db: AsyncSession, p: Principal) -> None:
    """Access tokens live 15 min; this makes logout and reuse-revocation take effect at once."""
    row = (
        await db.execute(
            select(Session.revoked_at, Session.expires_at).where(
                Session.id == p.session_id, Session.user_id == p.user_id
            )
        )
    ).first()
    if row is None or row.revoked_at is not None or row.expires_at <= rt.clock.now():
        raise ApiError("unauthorized", SIGN_IN_AGAIN)


async def revoke_session(rt: Runtime, db: AsyncSession, p: Principal) -> None:
    await db.execute(
        update(Session)
        .where(Session.id == p.session_id, Session.user_id == p.user_id)
        .values(revoked_at=rt.clock.now())
    )
    audit(db, p.user_id, "logout", actor=f"device:{p.device_id}", target=f"session:{p.session_id}")
    await db.commit()


async def revoke_device(
    db: AsyncSession, user_id: uuid.UUID, device_id: uuid.UUID, now: datetime
) -> None:
    await db.execute(
        update(Session)
        .where(
            Session.user_id == user_id,
            Session.device_id == device_id,
            Session.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )


def _tokens(rt: Runtime, p: Principal, refresh_token: str) -> dict[str, Any]:
    return {
        "access_token": issue_access(rt.settings, rt.clock, p),
        "access_expires_in": ACCESS_TTL_S,
        "refresh_token": refresh_token,
        "device_id": str(p.device_id),
    }
