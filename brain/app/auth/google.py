"""Sign in with Google (OIDC) for desktop apps.

1. The app opens /v2/auth/google/start in the system browser with a PKCE code_challenge and the
   port of its loopback listener (RFC 8252). The brain stores state + nonce in Redis.
2. Google redirects to /v2/auth/google/callback. The brain swaps the code for an id_token, checks
   it, and redirects to http://127.0.0.1:<port>/callback with a one-time login code (60 s).
3. The app posts the login code + code_verifier to /v2/auth/google/exchange and gets tokens.
   A login code is useless without the verifier, so another local app catching the redirect
   gains nothing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import uuid
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import sessions
from app.auth.sessions import DeviceIn
from app.core.errors import ApiError
from app.core.runtime import Runtime
from app.core.security import pkce_s256

logger = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 (a URL, not a secret)
ISSUERS = {"https://accounts.google.com", "accounts.google.com"}
STATE_TTL_S = 600
LOGIN_CODE_TTL_S = 60


class GoogleStartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_name: str = Field(min_length=1, max_length=60)
    platform: str | None = Field(default=None, max_length=40)
    device_id: uuid.UUID | None = None
    code_challenge: str = Field(pattern=r"^[A-Za-z0-9_-]{43,128}$")
    port: int = Field(ge=1024, le=65535)


class GoogleExchangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=20, max_length=100)
    code_verifier: str = Field(pattern=r"^[A-Za-z0-9._~-]{43,128}$")


class BrowserError(Exception):
    """Shown as a small page in the user's browser; we can't reach the app from here."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _redirect_uri(rt: Runtime) -> str:
    return f"{rt.settings.public_url.rstrip('/')}/v2/auth/google/callback"


def _loopback(port: int, **params: str) -> str:
    return f"http://127.0.0.1:{port}/callback?{urlencode(params)}"


async def start(rt: Runtime, q: GoogleStartIn) -> str:
    if not rt.settings.google_client_id:
        raise BrowserError("Google sign-in isn't set up on this brain yet. Use your email for now.")
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    flow = q.model_dump(mode="json") | {"nonce": nonce}
    await rt.redis.set(f"oauth:google:state:{state}", json.dumps(flow), ex=STATE_TTL_S)
    return f"{AUTH_URL}?" + urlencode(
        {
            "client_id": rt.settings.google_client_id,
            "redirect_uri": _redirect_uri(rt),
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "prompt": "select_account",
        }
    )


async def callback(rt: Runtime, code: str | None, state: str | None, error: str | None) -> str:
    """Returns the loopback URL to redirect to. Raises BrowserError when the flow is unknown."""
    raw = await rt.redis.getdel(f"oauth:google:state:{state}") if state else None
    if raw is None:
        raise BrowserError("That sign-in link expired. Head back to Spark and try again.")
    flow = json.loads(raw)
    port = int(flow["port"])
    if error or not code:
        return _loopback(port, error="cancelled")
    try:
        claims = await _id_token_claims(rt, code, flow["nonce"])
    except _GoogleRejected as exc:
        logger.warning("google sign-in rejected", extra={"reason": str(exc)})
        return _loopback(port, error="failed")
    login_code = secrets.token_urlsafe(32)
    payload = {
        "challenge": flow["code_challenge"],
        "device": {
            "name": flow["device_name"],
            "platform": flow["platform"],
            "id": flow["device_id"],
        },
        "sub": claims["sub"],
        "email": claims["email"].lower(),
        "name": claims.get("name"),
    }
    await rt.redis.set(f"oauth:google:login:{login_code}", json.dumps(payload), ex=LOGIN_CODE_TTL_S)
    return _loopback(port, code=login_code)


async def exchange(rt: Runtime, db: AsyncSession, body: GoogleExchangeIn) -> dict[str, Any]:
    raw = await rt.redis.getdel(f"oauth:google:login:{body.code}")
    if raw is None:
        raise ApiError("unauthorized", "That sign-in took too long. Give it another go.")
    flow = json.loads(raw)
    if not secrets.compare_digest(pkce_s256(body.code_verifier), flow["challenge"]):
        raise ApiError("unauthorized", "That sign-in didn't check out. Give it another go.")
    user = await sessions.find_or_create_user(
        db, email=flow["email"], provider="google", subject=flow["sub"], name=flow["name"]
    )
    device = DeviceIn.model_validate(flow["device"])
    return await sessions.sign_in(rt, db, user, device, method="google")


class _GoogleRejected(Exception):
    pass


async def _id_token_claims(rt: Runtime, code: str, nonce: str) -> dict[str, Any]:
    try:
        async with asyncio.timeout(10):
            r = await rt.http.post(
                TOKEN_URL,
                data={
                    "code": code,
                    "client_id": rt.settings.google_client_id,
                    "client_secret": rt.settings.google_client_secret.get_secret_value(),
                    "redirect_uri": _redirect_uri(rt),
                    "grant_type": "authorization_code",
                },
            )
        r.raise_for_status()
        id_token = r.json()["id_token"]
        # The token came straight from Google's token endpoint over TLS, so OIDC Core §3.1.3.7
        # lets TLS stand in for the signature check. Every other claim is still checked.
        claims: dict[str, Any] = jwt.decode(id_token, options={"verify_signature": False})
    except (httpx.HTTPError, TimeoutError, KeyError, ValueError, jwt.PyJWTError) as exc:
        raise _GoogleRejected(type(exc).__name__) from None
    if claims.get("iss") not in ISSUERS or claims.get("aud") != rt.settings.google_client_id:
        raise _GoogleRejected("issuer/audience")
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise _GoogleRejected("nonce")
    if float(claims.get("exp", 0)) <= rt.clock.now().timestamp():
        raise _GoogleRejected("expired")
    if not claims.get("email") or claims.get("email_verified") is not True or not claims.get("sub"):
        raise _GoogleRejected("email not verified")
    return claims
