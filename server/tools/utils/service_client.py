import time
from typing import Any, Dict, Optional, Tuple

_SERVICE_CACHE: Dict[Tuple[str, Optional[str]], Tuple[float, Any]] = {}
CACHE_TTL_SECONDS = 3000  # 50 minutes


async def get_gmail_service(user_id: str, account_email: Optional[str] = None):
    """Build the Gmail service directly in-process and cache it briefly."""
    cache_key = (user_id, account_email)
    now = time.time()

    if cache_key in _SERVICE_CACHE:
        cached_time, cached_service = _SERVICE_CACHE[cache_key]
        if now - cached_time < CACHE_TTL_SECONDS:
            return cached_service

    from app.features.gmail._client import get_gmail_service as build_gmail_service

    service = await build_gmail_service(user_id=user_id, account_email=account_email)
    _SERVICE_CACHE[cache_key] = (now, service)
    return service
