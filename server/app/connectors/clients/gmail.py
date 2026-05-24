"""Gmail API client builder with in-memory caching."""
import logging
import time
from typing import Any, Dict, Optional, Tuple

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.connectors.oauth.token_refresh import get_valid_access_token

logger = logging.getLogger(__name__)

_SERVICE_CACHE: Dict[Tuple[str, Optional[str]], Tuple[float, Any]] = {}
_CACHE_TTL = 3000  # 50 minutes (access tokens last 60 min)


async def get_gmail_service(user_id: str, account_email: Optional[str] = None):
    """
    Build and return an authenticated Gmail API service object.
    Caches the service instance for 50 minutes to avoid re-building.

    This is the ONLY entry point for Gmail API access.
    Tools call this — they never touch tokens directly.
    """
    cache_key = (user_id, account_email)
    now = time.time()

    if cache_key in _SERVICE_CACHE:
        cached_time, cached_service = _SERVICE_CACHE[cache_key]
        if now - cached_time < _CACHE_TTL:
            return cached_service

    access_token = await get_valid_access_token(
        user_id=user_id,
        service="gmail",
        account_email=account_email,
    )

    if not access_token:
        raise RuntimeError(f"No Gmail access token for user {user_id}. Please connect Gmail.")

    creds = Credentials(token=access_token)
    service = build("gmail", "v1", credentials=creds)

    _SERVICE_CACHE[cache_key] = (now, service)
    logger.debug("Gmail service built for user=%s", user_id)
    return service
