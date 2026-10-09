"""Access JWTs and the hashes behind OTPs, refresh tokens, and PKCE."""

from __future__ import annotations

import base64
import hashlib
import hmac
import uuid
from dataclasses import dataclass

import jwt

from app.core.clock import Clock
from app.core.config import Settings
from app.core.errors import SIGN_IN_AGAIN, ApiError

ACCESS_TTL_S = 15 * 60


@dataclass(frozen=True)
class Principal:
    """Who is calling. The only source of user identity in the brain (RULES §3)."""

    user_id: uuid.UUID
    device_id: uuid.UUID
    session_id: uuid.UUID


def issue_access(settings: Settings, clock: Clock, p: Principal) -> str:
    now = int(clock.now().timestamp())
    claims = {
        "typ": "access",
        "sub": str(p.user_id),
        "did": str(p.device_id),
        "sid": str(p.session_id),
        "iat": now,
        "exp": now + ACCESS_TTL_S,
    }
    return jwt.encode(claims, settings.jwt_secret.get_secret_value(), algorithm="HS256")


def decode_access(settings: Settings, clock: Clock, token: str) -> Principal:
    """Raises `unauthorized` for anything that isn't a live access token we signed.
    Expiry is checked against the injected clock, so tests can move time."""
    keys = [settings.jwt_secret]
    if settings.jwt_secret_previous is not None:
        keys.append(settings.jwt_secret_previous)
    for key in keys:
        try:
            claims = jwt.decode(
                token,
                key.get_secret_value(),
                algorithms=["HS256"],
                options={"verify_exp": False, "require": ["typ", "sub", "did", "sid", "exp"]},
            )
        except jwt.InvalidSignatureError:
            continue
        except jwt.PyJWTError:
            break
        if claims["typ"] != "access" or claims["exp"] <= clock.now().timestamp():
            break
        try:
            return Principal(
                uuid.UUID(claims["sub"]), uuid.UUID(claims["did"]), uuid.UUID(claims["sid"])
            )
        except (ValueError, TypeError):
            break
    raise ApiError("unauthorized", SIGN_IN_AGAIN)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def otp_hash(settings: Settings, email: str, code: str) -> str:
    """Keyed so a leaked otp_codes table can't be brute-forced offline (only 10^6 codes)."""
    key = hashlib.sha256(b"spark-otp:" + settings.jwt_secret.get_secret_value().encode()).digest()
    return hmac.new(key, f"{email.lower()}:{code}".encode(), hashlib.sha256).hexdigest()


def pkce_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
