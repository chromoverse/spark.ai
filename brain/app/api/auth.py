from __future__ import annotations

import html
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import Db, Me, Rt, client_ip
from app.auth import google, otp, sessions
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


def _page(message: str, status: int) -> HTMLResponse:
    body = (
        "<!doctype html><meta charset=utf-8><title>Spark</title>"
        "<body style='font-family:system-ui;max-width:28rem;margin:20vh auto;text-align:center'>"
        f"<h2>Spark</h2><p>{html.escape(message)}</p></body>"
    )
    return HTMLResponse(body, status_code=status)


@router.get("/google/start")
async def google_start(
    q: Annotated[google.GoogleStartIn, Query()], request: Request, rt: Rt
) -> Response:
    await hit(rt.redis, "google_start", client_ip(request), limit=20, window_s=600)
    try:
        return RedirectResponse(await google.start(rt, q), status_code=302)
    except google.BrowserError as exc:
        return _page(exc.message, 503)


@router.get("/google/callback")
async def google_callback(
    rt: Rt, code: str | None = None, state: str | None = None, error: str | None = None
) -> Response:
    try:
        return RedirectResponse(await google.callback(rt, code, state, error), status_code=302)
    except google.BrowserError as exc:
        return _page(exc.message, 400)


@router.post("/google/exchange")
async def google_exchange(
    body: google.GoogleExchangeIn, request: Request, rt: Rt, db: Db
) -> dict[str, Any]:
    await hit(rt.redis, "google_exchange", client_ip(request), limit=30, window_s=600)
    return ok(await google.exchange(rt, db, body))
