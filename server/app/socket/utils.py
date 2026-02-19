"""
Socket Utilities - Generic emit helpers usable from anywhere in the server.

Usage:
    from app.socket.utils import socket_emit, emit_server_status

No initialization needed — imports directly from server.py.
"""

from typing import Any, Optional, Literal
import logging
from datetime import datetime, timezone

from app.socket.server import sio, connected_users
from app.socket.user_utils import get_user_by_sid

logger = logging.getLogger(__name__)


# ==================== CORE EMIT FUNCTIONS ====================

async def socket_emit(event: str, data: Any, user_id: Optional[str] = None) -> bool:
    """
    Emit an event to a specific user or broadcast to all.
    
    Usage:
        await socket_emit('notification', {'msg': 'hi'}, user_id='user123')
        await socket_emit('announcement', {'msg': 'hi'})  # broadcast
    """
    try:
        if user_id:
            sids = connected_users.get(user_id, set())
            if sids:
                for sid in sids:
                    await sio.emit(event, data, room=sid)
                logger.info(f"✅ Emitted '{event}' to user {user_id}")
                return True
            else:
                logger.warning(f"⚠️ User {user_id} not connected")
                return False
        else:
            await sio.emit(event, data)
            logger.info(f"📢 Broadcasted '{event}' to all users")
            return True
    except Exception as e:
        logger.error(f"❌ Error emitting '{event}': {e}")
        return False


async def socket_emit_to_users(event: str, data: Any, user_ids: list[str]) -> dict:
    """
    Emit an event to multiple specific users.
    Returns: {'success': int, 'failed': int, 'total': int}
    """
    success_count = 0
    failed_count = 0

    for uid in user_ids:
        result = await socket_emit(event, data, user_id=uid)
        if result:
            success_count += 1
        else:
            failed_count += 1

    logger.info(f"📊 Emitted '{event}' — Success: {success_count}, Failed: {failed_count}")
    return {
        'success': success_count,
        'failed': failed_count,
        'total': len(user_ids)
    }


async def socket_emit_to_room(room: str, event: str, data: Any) -> bool:
    """Emit an event to all users in a room."""
    try:
        await sio.emit(event, data, room=room)
        logger.info(f"📢 Emitted '{event}' to room '{room}'")
        return True
    except Exception as e:
        logger.error(f"❌ Error emitting to room '{room}': {e}")
        return False


# ==================== STATUS & NOTIFICATIONS ====================

async def emit_server_status(
    status: str,
    flag: Literal["INFO", "WARN", "ERROR"],
    sid: str
) -> bool:
    """
    Emit a server-status message to a specific client by SID.
    
    Usage:
        await emit_server_status("Processing...", "INFO", sid)
    """
    user_id = get_user_by_sid(sid)
    return await socket_emit(
        "server-status",
        {
            "flag": flag,
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat()
        },
        user_id
    )


async def notify_user(user_id: str, message: str, notification_type: str = 'info') -> bool:
    """Send a notification to a specific user."""
    return await socket_emit('notification', {
        'message': message,
        'type': notification_type
    }, user_id=user_id)


async def notify_all(message: str, notification_type: str = 'info') -> bool:
    """Send a notification to all connected users."""
    return await socket_emit('notification', {
        'message': message,
        'type': notification_type
    })


# ==================== ONLINE STATUS ====================

def is_user_online(user_id: str) -> bool:
    """Check if a user is currently connected."""
    return user_id in connected_users


def get_online_users() -> list[str]:
    """Get list of all currently connected user IDs."""
    return list(connected_users.keys())


def get_online_count() -> int:
    """Get count of currently connected users."""
    return len(connected_users)


# ==================== TTS STREAMING ====================

async def stream_tts_to_client(
    text: str,
    user_id: Optional[str] = None,
    gender: str = "female"
) -> bool:
    """
    Stream TTS audio to connected client(s) via socket.
    
    Falls back to printing if no client is connected (manual testing).
    
    How it works:
    - connected_users is a Dict[str, Set[str]]  →  { user_id: {sid1, sid2, ...} }
    - Each user can have multiple socket sessions (e.g. multiple browser tabs)
    - If user_id is given, TTS streams only to THAT user's sessions
    - If user_id is None, TTS broadcasts to ALL connected sessions
    
    Args:
        text:     The text to convert to speech and stream
        user_id:  Target a specific user (None = broadcast to all)
        gender:   Voice gender for TTS ("male" or "female")
    
    Returns:
        True if TTS was streamed, False if fell back to print
    
    Usage:
        from app.socket.utils import stream_tts_to_client
        
        # Target specific user
        await stream_tts_to_client("Hello!", user_id="user123")
        
        # Broadcast to everyone
        await stream_tts_to_client("Hello everyone!")
    """
    import asyncio
    
    if not text:
        return False

    try:
        from app.services.tts_services import tts_service

        # Collect target SIDs
        target_sids: set[str] = set()

        if user_id:
            # Target specific user's sessions
            target_sids = connected_users.get(user_id, set())
            if not target_sids:
                logger.warning(f"⚠️ User '{user_id}' not connected, falling back to print")
                print(f"\n🔊 [TTS would say]: {text}\n")
                return False
        else:
            # Broadcast to all connected sessions
            for user_sids in connected_users.values():
                target_sids.update(user_sids)

        if not target_sids:
            logger.info("🔇 No socket clients connected (manual testing mode)")
            print(f"\n🔊 [TTS would say]: {text}\n")
            return False

        # Stream TTS to each connected session (non-blocking)
        for sid in target_sids:
            logger.info(f"📡 Streaming TTS to socket {sid}")
            asyncio.create_task(
                tts_service.stream_to_socket(
                    sio=sio, sid=sid, text=text, gender=gender
                )
            )

        return True

    except Exception as e:
        logger.error(f"❌ TTS streaming failed: {e}")
        print(f"\n🔊 [TTS fallback]: {text}\n")
        return False
