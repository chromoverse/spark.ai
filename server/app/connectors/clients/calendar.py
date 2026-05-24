"""Google Calendar API client builder."""
import logging
from typing import Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.connectors.oauth.token_refresh import get_valid_access_token
from app.connectors.clients.base import ClientCache

logger = logging.getLogger(__name__)
_cache = ClientCache(ttl_seconds=3000)


async def get_calendar_service(user_id: str, account_email: Optional[str] = None):
    """
    Build and return an authenticated Google Calendar API service.
    Tools call this — they never touch tokens directly.
    """
    cache_key = f"{user_id}:{account_email or 'default'}"
    cached = _cache.get(cache_key)
    if cached:
        return cached

    access_token = await get_valid_access_token(
        user_id=user_id,
        service="google_calendar",
        account_email=account_email,
    )
    if not access_token:
        raise RuntimeError(f"No Calendar token for user {user_id}. Please connect Google Calendar.")

    creds = Credentials(token=access_token)
    service = build("calendar", "v3", credentials=creds)
    _cache.set(cache_key, service)
    return service
