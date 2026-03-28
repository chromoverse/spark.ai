"""
Access-token lifecycle manager (service-agnostic).

  • access_token → local only (SQLite via LocalKVManager, TTL-based)
  • On cache miss → fetch refresh_token via oauth_token_service
                   → exchange with provider for a fresh access_token
                   → cache locally with TTL
"""

import logging
import os
import httpx
from typing import Optional

from app.cache.local_kv_manager import LocalKVManager
from app.features.external_service.oauth_token_service import (
    get_refresh_token,
    revoke_token,
    save_token,
)
from app.features.external_service.providers import (
    get_provider,
    get_client_id,
    get_client_secret,
)

logger = logging.getLogger(__name__)

# Google access tokens last 3600s — we refresh 60s early to avoid edge-case expiry
_ACCESS_TOKEN_TTL = 3540


def _cache_key(
    user_id: str, service: str, account_email: Optional[str] = None
) -> str:
    """Consistent key format for access-token cache entries."""
    base = f"oauth_access_token:{service}:{user_id}"
    return f"{base}:{account_email}" if account_email else base


# ── Public API ────────────────────────────────────────────────────────────────

async def get_valid_access_token(
    user_id: str,
    service: str = "gmail",
    account_email: Optional[str] = None,
) -> Optional[str]:
    """
    Returns a valid access token for the given user + service.

    Flow:
      1. Check LocalKVManager cache (sub-ms)
      2. On miss → fetch refresh_token (local first, then MongoDB)
      3. Exchange with provider's token endpoint → fresh access_token
      4. Cache locally with TTL
      5. Return access_token
    """
    kv = LocalKVManager()
    key = _cache_key(user_id, service, account_email)

    # ── 1. Cache hit ──────────────────────────────────────────────────────
    cached = await kv.get(key)
    if cached:
        return cached

    # ── 2. Fetch refresh token ────────────────────────────────────────────
    refresh_token = await get_refresh_token(user_id, service, account_email)
    if not refresh_token:
        raise RuntimeError(
            f"No active {service} token for user {user_id}. Re-auth required."
        )

    # ── 3. Exchange for new access token ──────────────────────────────────
    access_token = await _refresh_access_token(
        user_id=user_id,
        service=service,
        refresh_token=refresh_token,
        account_email=account_email,
    )

    # ── 4. Cache locally with TTL ─────────────────────────────────────────
    await kv.set(key, access_token, ex=_ACCESS_TOKEN_TTL)

    return access_token


async def clear_access_token_cache(
    user_id: str,
    service: str = "gmail",
    account_email: Optional[str] = None,
) -> None:
    """Force-evict cached access token (e.g. after revocation)."""
    kv = LocalKVManager()
    key = _cache_key(user_id, service, account_email)
    await kv.delete(key)


# ── Internal ──────────────────────────────────────────────────────────────────

async def _refresh_access_token(
    user_id: str,
    service: str,
    refresh_token: str,
    account_email: Optional[str],
) -> str:
    """
    Exchange a refresh_token for a new access_token via the provider's
    token endpoint.  Handles the `invalid_grant` case gracefully.
    """
    provider = get_provider(service)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            provider["token_uri"],
            data={
                "client_id": get_client_id(service),
                "client_secret": get_client_secret(service),
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )

    data = resp.json()

    # ── Token revoked by user ─────────────────────────────────────────────
    if "error" in data:
        if data["error"] == "invalid_grant":
            logger.warning(
                "Refresh token revoked for user=%s service=%s — marking inactive.",
                user_id, service,
            )
            await revoke_token(user_id, service, account_email)
            raise RuntimeError(
                f"{service} access revoked by user {user_id}. Please reconnect."
            )
        raise RuntimeError(f"Token refresh failed: {data}")

    access_token = data["access_token"]

    # ── Provider sometimes rotates refresh token — update both stores ─────
    if "refresh_token" in data:
        logger.info(
            "Provider rotated refresh token for user=%s service=%s — updating stores.",
            user_id, service,
        )
        await save_token(
            user_id=user_id,
            service=service,
            refresh_token=data["refresh_token"],
            account_email=account_email,
        )

    logger.debug(
        "Access token refreshed for user=%s service=%s", user_id, service
    )
    return access_token
