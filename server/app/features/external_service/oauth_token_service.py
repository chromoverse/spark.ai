"""
Service-agnostic OAuth token CRUD.

Dual-write strategy:
  • refresh_token → encrypted → saved to MongoDB (cloud) AND LocalKVManager (local SQLite)
  • Reads try local first (sub-ms), fall back to MongoDB if local miss

No service-specific logic lives here — providers.py holds per-service config.
"""

import logging
from datetime import datetime
from typing import Optional

from app.db.mongo import get_db
from app.cache.local_kv_manager import LocalKVManager
from app.features.external_service.encryption import encrypt_token, decrypt_token

logger = logging.getLogger(__name__)


# ── Key helpers ───────────────────────────────────────────────────────────────

def _local_refresh_key(
    user_id: str, service: str, account_email: Optional[str] = None
) -> str:
    """SQLite key for the encrypted refresh token."""
    base = f"oauth_refresh_token:{service}:{user_id}"
    return f"{base}:{account_email}" if account_email else base


# ── SAVE ──────────────────────────────────────────────────────────────────────

async def save_token(
    user_id: str,
    service: str,
    refresh_token: str,
    account_email: Optional[str] = None,
    scope: Optional[str] = None,
) -> bool:
    """
    Encrypt and persist a refresh token to BOTH local SQLite and MongoDB.
    Called once after the user completes the OAuth consent flow.
    """
    try:
        encrypted = encrypt_token(refresh_token)

        # ── Local (SQLite) ────────────────────────────────────────────────
        kv = LocalKVManager()
        local_key = _local_refresh_key(user_id, service, account_email)
        await kv.set(local_key, encrypted)  # no TTL — permanent until revoked

        # ── Cloud (MongoDB) ───────────────────────────────────────────────
        db = get_db()
        await db.oauth_tokens.update_one(
            {
                "user_id": user_id,
                "service": service,
                "account_email": account_email,
            },
            {
                "$set": {
                    "refresh_token": encrypted,
                    "scope": scope,
                    "is_active": True,
                    "connected_at": datetime.utcnow(),
                    "last_refreshed": None,
                }
            },
            upsert=True,
        )

        logger.info(
            "Token saved (local+cloud) for user=%s service=%s email=%s",
            user_id, service, account_email,
        )
        return True

    except Exception as e:
        logger.error("save_token failed: %s", e)
        return False


# ── GET ───────────────────────────────────────────────────────────────────────

async def get_refresh_token(
    user_id: str,
    service: str,
    account_email: Optional[str] = None,
) -> Optional[str]:
    """
    Fetch and decrypt the refresh token.
    Tries local SQLite first (sub-ms), falls back to MongoDB.
    """
    try:
        kv = LocalKVManager()
        local_key = _local_refresh_key(user_id, service, account_email)

        # ── 1. Local hit ──────────────────────────────────────────────────
        encrypted = await kv.get(local_key)
        if encrypted:
            return decrypt_token(encrypted)

        # ── 2. Fallback to MongoDB ────────────────────────────────────────
        db = get_db()
        query = {"user_id": user_id, "service": service, "is_active": True}
        if account_email:
            query["account_email"] = account_email

        doc = await db.oauth_tokens.find_one(query)
        if not doc:
            logger.warning(
                "No active token for user=%s service=%s", user_id, service
            )
            return None

        # Back-fill local cache so next read is instant
        await kv.set(local_key, doc["refresh_token"])

        return decrypt_token(doc["refresh_token"])

    except Exception as e:
        logger.error("get_refresh_token failed: %s", e)
        return None


# ── REVOKE ────────────────────────────────────────────────────────────────────

async def revoke_token(
    user_id: str,
    service: str,
    account_email: Optional[str] = None,
) -> bool:
    """Soft-delete: mark inactive in MongoDB + remove from local SQLite."""
    try:
        # ── Local ─────────────────────────────────────────────────────────
        kv = LocalKVManager()
        local_key = _local_refresh_key(user_id, service, account_email)
        await kv.delete(local_key)

        # ── Cloud ─────────────────────────────────────────────────────────
        db = get_db()
        query = {"user_id": user_id, "service": service}
        if account_email:
            query["account_email"] = account_email

        await db.oauth_tokens.update_one(query, {"$set": {"is_active": False}})

        logger.info(
            "Token revoked for user=%s service=%s email=%s",
            user_id, service, account_email,
        )
        return True

    except Exception as e:
        logger.error("revoke_token failed: %s", e)
        return False


# ── STATUS CHECK ──────────────────────────────────────────────────────────────

async def is_connected(user_id: str, service: str) -> bool:
    """Quick check — does this user have an active token for this service?"""
    try:
        # Try local first
        kv = LocalKVManager()
        local_key = _local_refresh_key(user_id, service)
        if await kv.get(local_key):
            return True

        # Fallback to cloud
        db = get_db()
        doc = await db.oauth_tokens.find_one(
            {"user_id": user_id, "service": service, "is_active": True},
            {"_id": 1},
        )
        return doc is not None

    except Exception as e:
        logger.error("is_connected check failed: %s", e)
        return False
