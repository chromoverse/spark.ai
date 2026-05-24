"""Slack Web API client builder."""
import logging
from typing import Optional

import httpx

from app.connectors.oauth.token_refresh import get_valid_access_token
from app.connectors.clients.base import ClientCache

logger = logging.getLogger(__name__)
_cache = ClientCache(ttl_seconds=3000)


class SlackClient:
    """Lightweight Slack Web API wrapper."""

    def __init__(self, access_token: str):
        self._token = access_token
        self._base = "https://slack.com/api"

    async def _call(self, method: str, **kwargs) -> dict:
        """Make an authenticated Slack API call."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._base}/{method}",
                headers={"Authorization": f"Bearer {self._token}"},
                json=kwargs if kwargs else None,
            )
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack API error: {data.get('error', 'unknown')}")
        return data

    async def list_channels(self, limit: int = 50) -> list:
        data = await self._call("conversations.list", limit=limit, types="public_channel,private_channel")
        return data.get("channels", [])

    async def channel_history(self, channel_id: str, limit: int = 20) -> list:
        data = await self._call("conversations.history", channel=channel_id, limit=limit)
        return data.get("messages", [])

    async def send_message(self, channel_id: str, text: str) -> dict:
        return await self._call("chat.postMessage", channel=channel_id, text=text)

    async def search_messages(self, query: str, count: int = 20) -> list:
        data = await self._call("search.messages", query=query, count=count)
        return data.get("messages", {}).get("matches", [])


async def get_slack_client(user_id: str, account_email: Optional[str] = None) -> SlackClient:
    """Build authenticated Slack client."""
    cache_key = f"{user_id}:{account_email or 'default'}"
    cached = _cache.get(cache_key)
    if cached:
        return cached

    access_token = await get_valid_access_token(
        user_id=user_id,
        service="slack",
        account_email=account_email,
    )
    if not access_token:
        raise RuntimeError(f"No Slack token for user {user_id}. Please connect Slack.")

    client = SlackClient(access_token)
    _cache.set(cache_key, client)
    return client
