import httpx
import time
from typing import Optional, Dict, Tuple, Any
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SERVER_BASE = "http://127.0.0.1:8000"  # or read from config

_SERVICE_CACHE: Dict[Tuple[str, Optional[str]], Tuple[float, Any]] = {}
CACHE_TTL_SECONDS = 3000  # 50 minutes

async def get_gmail_service(user_id: str, account_email: Optional[str] = None):
    """Fetch access token from server, build Gmail service locally, and cache it."""
    cache_key = (user_id, account_email)
    now = time.time()
    
    if cache_key in _SERVICE_CACHE:
        cached_time, cached_service = _SERVICE_CACHE[cache_key]
        if now - cached_time < CACHE_TTL_SECONDS:
            return cached_service

    params = {"user_id": user_id}
    if account_email:
        params["account_email"] = account_email
    
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{SERVER_BASE}/auth/internal/token/gmail", params=params)
        resp.raise_for_status()
        access_token = resp.json()["access_token"]
    
    creds = Credentials(token=access_token)
    service = build("gmail", "v1", credentials=creds)
    
    _SERVICE_CACHE[cache_key] = (now, service)
    return service
