"""
User Utilities - Session and connection helpers for socket users.

Usage anywhere in the server:
    from app.socket.user_utils import get_user_from_session, send_to_user
"""

import logging
from app.socket.server import sio, connected_users

logger = logging.getLogger(__name__)


async def get_user_from_session(sid: str) -> str:
    """
    Get authenticated user_id from socket session.
    Raises ValueError if not authenticated.
    """
    try:
        session = await sio.get_session(sid)
        user_id = session.get("user_id")

        if not user_id:
            raise ValueError("No user_id in session - socket not authenticated")

        return user_id
    except Exception as e:
        logger.error(f"❌ Failed to get user from session: {e}")
        raise


async def send_to_user(user_id: str, event: str, data: dict) -> bool:
    """
    Send event to ALL connections of a specific user.
    Supports multi-device / multi-tab.
    """
    if user_id in connected_users:
        sids = connected_users[user_id]
        for sid in sids:
            await sio.emit(event, data, to=sid)
        logger.info(f"📤 Sent {event} to user {user_id} ({len(sids)} connections)")
        return True
    else:
        logger.warning(f"⚠️ User {user_id} not connected")
        return False


def get_connected_users() -> list[str]:
    """Get list of connected user IDs."""
    return list(connected_users.keys())


def get_user_by_sid(sid: str) -> str | None:
    """Reverse-lookup: find user_id by session ID."""
    for user_id, sids in connected_users.items():
        if sid in sids:
            return user_id
    return None


async def serialize_response(chat_res) -> dict:
    """Safely serialize a chat response to dict."""
    if chat_res is None:
        return {"error": "No response from chat service"}

    if hasattr(chat_res, "model_dump") and callable(getattr(chat_res, "model_dump")):
        return chat_res.model_dump()
    elif hasattr(chat_res, "dict") and callable(getattr(chat_res, "dict")):
        return chat_res.dict()
    else:
        try:
            return dict(chat_res)
        except Exception:
            return {"response": str(chat_res)}
