"""Google Drive API client builder."""
import logging
from typing import Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.connectors.oauth.token_refresh import get_valid_access_token
from app.connectors.clients.base import ClientCache

logger = logging.getLogger(__name__)
_cache = ClientCache(ttl_seconds=3000)


async def get_drive_service(user_id: str, account_email: Optional[str] = None):
    """Build authenticated Google Drive API service."""
    cache_key = f"{user_id}:{account_email or 'default'}"
    cached = _cache.get(cache_key)
    if cached:
        return cached

    access_token = await get_valid_access_token(
        user_id=user_id,
        service="google_drive",
        account_email=account_email,
    )
    if not access_token:
        raise RuntimeError(f"No Drive token for user {user_id}. Please connect Google Drive.")

    creds = Credentials(token=access_token)
    service = build("drive", "v3", credentials=creds)
    _cache.set(cache_key, service)
    return service
