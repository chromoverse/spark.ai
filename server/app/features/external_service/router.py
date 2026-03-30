"""
Generic OAuth router — works for ANY registered provider.

Routes:
  GET    /auth/{service}/connect?user_id=...     → redirect to provider consent
  GET    /auth/{service}/callback?code=&state=    → exchange code, save tokens
  DELETE /auth/{service}/disconnect?user_id=...   → revoke + clear cache
  GET    /auth/{service}/status?user_id=...       → connection check
"""

import logging
import os
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow

from app.cache.local_kv_manager import LocalKVManager
from app.features.external_service.oauth_token_service import (
    save_token,
    revoke_token,
    is_connected,
)
from app.features.external_service.token_manager import clear_access_token_cache, get_valid_access_token
from app.features.external_service.providers import get_provider, get_redirect_uri, PROVIDERS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["OAuth Services"])

# Needed so google-auth doesn't throw when Google returns slightly different scopes
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_google_flow(service: str) -> Flow:
    """Build a Google OAuth Flow from the provider registry."""
    cfg = get_provider(service)
    redirect_uri = get_redirect_uri(service)

    flow = Flow.from_client_config(
        client_config={
            "web": {
                "client_id": os.getenv(cfg["client_id_env"]),
                "client_secret": os.getenv(cfg["client_secret_env"]),
                "redirect_uris": [redirect_uri],
                "auth_uri": cfg["auth_uri"],
                "token_uri": cfg["token_uri"],
            }
        },
        scopes=cfg["scopes"],
        redirect_uri=redirect_uri,
    )
    flow.oauth2session.scope_changed_exception_class = None
    return flow


# ── GET /auth/{service}/connect ───────────────────────────────────────────────

@router.get("/{service}/connect")
async def oauth_connect(service: str, request: Request, user_id: str):
    """
    Step 1: Redirect user to the provider's OAuth consent screen.
    Frontend calls this with the logged-in user_id.
    """
    cfg = get_provider(service)  # validates service name

    # Currently all providers are Google-based; future: branch on provider type
    flow = _build_google_flow(service)
    auth_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=f"{service}:{user_id}",  # encode service into state
        include_granted_scopes="true",
    )

    # Persist code_verifier so the callback can use the same Flow state
    if flow.code_verifier:
        kv = LocalKVManager()
        await kv.set(
            f"oauth_code_verifier:{service}:{user_id}",
            flow.code_verifier,
            ex=600,  # 10 min TTL — enough to complete OAuth
        )

    return RedirectResponse(auth_url)


# ── GET /auth/{service}/callback ──────────────────────────────────────────────

@router.get("/{service}/callback")
async def oauth_callback(service: str, request: Request, code: str, state: str):
    """
    Step 2: Provider redirects here after user grants permission.
    Exchanges auth code for tokens, saves refresh_token to both local + cloud.
    """
    # state format: "service:user_id"
    parts = state.split(":", 1)
    if len(parts) != 2 or parts[0] != service:
        raise HTTPException(status_code=400, detail="Invalid OAuth state parameter")
    user_id = parts[1]

    try:
        cfg = get_provider(service)
        flow = _build_google_flow(service)

        # Restore code_verifier from cache
        kv = LocalKVManager()
        verifier_key = f"oauth_code_verifier:{service}:{user_id}"
        code_verifier = await kv.get(verifier_key)
        if code_verifier:
            flow.code_verifier = code_verifier
            await kv.delete(verifier_key)

        flow.fetch_token(code=code)
        creds = flow.credentials

        if not creds.refresh_token:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"No refresh token returned. "
                    f"Try disconnecting and reconnecting {cfg['display_name']}."
                ),
            )

        # ── Resolve account email (if provider has a userinfo endpoint) ───
        account_email = None
        if cfg.get("userinfo_uri"):
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    cfg["userinfo_uri"],
                    headers={"Authorization": f"Bearer {creds.token}"},
                )
            if resp.status_code == 200:
                account_email = resp.json().get("email")

        # ── Save tokens (local + cloud) ───────────────────────────────────
        await save_token(
            user_id=user_id,
            service=service,
            refresh_token=creds.refresh_token,
            account_email=account_email,
            scope=" ".join(cfg["scopes"]),
        )

        logger.info(
            "%s connected for user=%s email=%s",
            cfg["display_name"], user_id, account_email,
        )

        # TODO: redirect to your frontend success page
        return {"status": "connected", "service": service, "email": account_email}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("%s callback failed: %s", service, e)
        raise HTTPException(status_code=500, detail=str(e))


# ── DELETE /auth/{service}/disconnect ─────────────────────────────────────────

@router.delete("/{service}/disconnect")
async def oauth_disconnect(
    service: str, user_id: str, account_email: Optional[str] = None
):
    """Soft-revoke: mark token inactive in both stores, clear access-token cache."""
    get_provider(service)  # validate

    await revoke_token(user_id, service, account_email)
    await clear_access_token_cache(user_id, service, account_email)

    logger.info("%s disconnected for user=%s", service, user_id)
    return {"status": "disconnected", "service": service}


# ── GET /auth/{service}/status ────────────────────────────────────────────────

@router.get("/{service}/status")
async def oauth_status(service: str, user_id: str):
    """Quick check — has this user connected this service?"""
    get_provider(service)  # validate

    connected = await is_connected(user_id, service)
    return {"service": service, "connected": connected}


# ── GET /internal/token/{service} ─────────────────────────────────────────────

@router.get("/internal/token/{service}")
async def internal_get_token(service: str, user_id: str, account_email: Optional[str] = None):
    """
    Internal endpoint to fetch a valid access token.
    Used by internal helpers that need to mint service instances locally.
    """
    try:
        get_provider(service)  # validate
        token = await get_valid_access_token(
            user_id=user_id, service=service, account_email=account_email
        )
        return {"access_token": token}
    except Exception as e:
        logger.error("Failed to get internal token for %s: %s", service, e)
        raise HTTPException(status_code=400, detail=str(e))
