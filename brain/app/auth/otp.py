"""Email one-time codes: 6 digits, stored as a keyed hash, 10 min life, 5 tries, 60 s cooldown."""

from __future__ import annotations

import asyncio
import hmac
import logging
import re
import secrets
from datetime import timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.core.runtime import Runtime
from app.core.security import otp_hash
from app.db.models import OtpCode

logger = logging.getLogger(__name__)

OTP_TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5
COOLDOWN_S = 60
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(raw: str) -> str:
    email = raw.strip().lower()
    if len(email) > 254 or not _EMAIL.match(email):
        raise ApiError("invalid_input", "That email doesn't look right. Mind checking it?")
    return email


async def start(rt: Runtime, db: AsyncSession, email: str) -> None:
    now = rt.clock.now()
    latest = await db.scalar(
        select(OtpCode).where(OtpCode.email == email).order_by(OtpCode.created_at.desc()).limit(1)
    )
    if latest is not None:
        wait = COOLDOWN_S - (now - latest.created_at).total_seconds()
        if wait > 0:
            raise ApiError(
                "rate_limited",
                "I just sent you a code. Give it a minute before asking for another.",
                retry_after_s=int(wait) + 1,
            )
    code = f"{secrets.randbelow(10**6):06d}"
    db.add(
        OtpCode(
            email=email,
            code_hash=otp_hash(rt.settings, email, code),
            expires_at=now + OTP_TTL,
            created_at=now,
        )
    )
    await db.flush()
    await _send(rt, email, code)  # before commit: a failed send leaves no cooldown behind
    await db.commit()


async def verify(rt: Runtime, db: AsyncSession, email: str, code: str) -> None:
    """Consumes the latest live code or raises. Attempts are counted under a row lock."""
    now = rt.clock.now()
    otp = await db.scalar(
        select(OtpCode)
        .where(OtpCode.email == email, OtpCode.consumed_at.is_(None))
        .order_by(OtpCode.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if otp is None or otp.expires_at <= now:
        raise ApiError("unauthorized", "That code has expired. Grab a new one and try again.")
    if otp.attempts >= MAX_ATTEMPTS:
        raise ApiError(
            "rate_limited", "Too many tries on that code. Grab a fresh one and we'll go again."
        )
    if not hmac.compare_digest(otp_hash(rt.settings, email, code), otp.code_hash):
        otp.attempts += 1
        await db.commit()
        left = MAX_ATTEMPTS - otp.attempts
        if left == 0:
            raise ApiError(
                "unauthorized",
                "That code didn't match, and that was the last try. Grab a fresh one.",
            )
        tries = "1 try" if left == 1 else f"{left} tries"
        raise ApiError("unauthorized", f"That code didn't match. {tries} left.")
    otp.consumed_at = now


async def _send(rt: Runtime, email: str, code: str) -> None:
    key = rt.settings.resend_api_key.get_secret_value()
    if not key:
        logger.error("RESEND_API_KEY is not set; email sign-in is unavailable")
        raise ApiError(
            "provider_unavailable", "Email sign-in isn't set up yet. Try Google for now."
        )
    try:
        async with asyncio.timeout(10):
            r = await rt.http.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "from": rt.settings.mail_from,
                    "to": [email],
                    "subject": f"{code} is your Spark code",
                    "text": (
                        f"Your Spark sign-in code is {code}.\n\n"
                        "It works for 10 minutes. Didn't ask for it? You can ignore this email."
                    ),
                },
            )
        r.raise_for_status()
    except (httpx.HTTPError, TimeoutError) as exc:
        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        logger.warning("otp email failed", extra={"provider": "resend", "status": status})
        raise ApiError(
            "provider_unavailable",
            "Couldn't send the code just now. Try again in a minute.",
            retry_after_s=30,
        ) from None
