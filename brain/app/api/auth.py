from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import Db, Me, Rt, client_ip
from app.auth import otp, sessions
from app.auth.sessions import DeviceIn
from app.core.errors import ok
from app.core.ratelimit import hit

router = APIRouter(prefix="/v2/auth")


class OtpStartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)


class OtpVerifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)
    code: str = Field(pattern=r"^\d{6}$")
    device: DeviceIn


class RefreshIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str = Field(min_length=10, max_length=200)


@router.post("/otp/start")
async def otp_start(body: OtpStartIn, request: Request, rt: Rt, db: Db) -> dict[str, Any]:
    # Per-IP cap stops one client from mailing codes to many addresses.
    await hit(rt.redis, "otp_start", client_ip(request), limit=10, window_s=600)
    await otp.start(rt, db, otp.normalize_email(body.email))
    return ok({"sent": True, "cooldown_s": otp.COOLDOWN_S})


@router.post("/otp/verify")
async def otp_verify(body: OtpVerifyIn, request: Request, rt: Rt, db: Db) -> dict[str, Any]:
    await hit(rt.redis, "otp_verify", client_ip(request), limit=30, window_s=600)
    email = otp.normalize_email(body.email)
    await otp.verify(rt, db, email, body.code)
    user = await sessions.find_or_create_user(db, email=email, provider="email", subject=email)
    return ok(await sessions.sign_in(rt, db, user, body.device, method="otp"))


@router.post("/refresh")
async def refresh(body: RefreshIn, request: Request, rt: Rt, db: Db) -> dict[str, Any]:
    await hit(rt.redis, "refresh", client_ip(request), limit=60, window_s=600)
    return ok(await sessions.rotate(rt, db, body.refresh_token))


@router.post("/logout")
async def logout(me: Me, rt: Rt, db: Db) -> dict[str, Any]:
    await sessions.revoke_session(rt, db, me)
    return ok({"signed_out": True})
