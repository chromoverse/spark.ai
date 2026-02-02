"""
WebSocket utility functions for easy event emission across the application.
Import these functions anywhere you need to send real-time updates.
"""

from typing import Any, Optional, Dict, Literal
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# This will be set when the socket server initializes
_sio = None
_connected_users : Dict[str, str] = {}


def init_socket_utils(sio_instance, connected_users_dict):
    """
    Initialize the socket utilities with the socket.io instance.
    Call this once during app startup.
    """
    global _sio, _connected_users
    _sio = sio_instance
    _connected_users = connected_users_dict
    logger.info("✅ Socket utilities initialized")


async def socket_emit(event: str, data: Any, user_id: Optional[str] = None) -> bool:
    """
    Main utility function to emit events.
    
    Usage:
        # Emit to specific user
        await socket_emit('notification', {'message': 'Hello'}, user_id='user123')
        
        # Emit to all users
        await socket_emit('announcement', {'message': 'Server maintenance'})
    
    Args:
        event: The event name
        data: The data to send
        user_id: Optional user ID to send to specific user
    
    Returns:
        bool: True if successful, False otherwise
    """
    if not _sio:
        logger.error("❌ Socket not initialized. Call init_socket_utils first.")
        return False
    
    try:
        if user_id:
            # Emit to specific user
            sid = _connected_users.get(user_id)
            if sid:
                await _sio.emit(event, data, room=sid)
                logger.info(f"✅ Emitted '{event}' to user {user_id}")
                return True
            else:
                logger.warning(f"⚠️ User {user_id} not connected")
                return False
        else:
            # Emit to all users
            await _sio.emit(event, data)
            logger.info(f"📢 Broadcasted '{event}' to all users")
            return True
    except Exception as e:
        logger.error(f"❌ Error emitting '{event}': {e}")
        return False


async def socket_emit_to_users(event: str, data: Any, user_ids: list[str]) -> dict:
    """
    Emit an event to multiple specific users.
    
    Usage:
        result = await socket_emit_to_users(
            'group-notification',
            {'message': 'New post'},
            user_ids=['user1', 'user2', 'user3']
        )
        # Returns: {'success': 2, 'failed': 1, 'total': 3}
    
    Args:
        event: The event name
        data: The data to send
        user_ids: List of user IDs
    
    Returns:
        dict: Summary of send results
    """
    if not _sio or not _connected_users:
        logger.error("❌ Socket not initialized")
        return {'success': 0, 'failed': len(user_ids), 'total': len(user_ids)}
    
    success_count = 0
    failed_count = 0
    
    for user_id in user_ids:
        sid = _connected_users.get(user_id)
        if sid:
            try:
                await _sio.emit(event, data, room=sid)
                success_count += 1
            except Exception as e:
                logger.error(f"❌ Failed to emit to {user_id}: {e}")
                failed_count += 1
        else:
            failed_count += 1
    
    logger.info(f"📊 Emitted '{event}' - Success: {success_count}, Failed: {failed_count}")
    return {
        'success': success_count,
        'failed': failed_count,
        'total': len(user_ids)
    }


async def socket_emit_to_room(room: str, event: str, data: Any) -> bool:
    """
    Emit an event to all users in a room.
    
    Usage:
        await socket_emit_to_room('chat_room_123', 'new-message', message_data)
    
    Args:
        room: The room name
        event: The event name
        data: The data to send
    
    Returns:
        bool: True if successful
    """
    if not _sio:
        logger.error("❌ Socket not initialized")
        return False
    
    try:
        await _sio.emit(event, data, room=room)
        logger.info(f"📢 Emitted '{event}' to room '{room}'")
        return True
    except Exception as e:
        logger.error(f"❌ Error emitting to room '{room}': {e}")
        return False


def is_user_online(user_id: str) -> bool:
    """
    Check if a user is currently connected.
    
    Usage:
        if is_user_online('user123'):
            await socket_emit('notification', data, user_id='user123')
        else:
            # Save notification to database for later
            pass
    
    Args:
        user_id: The user's ID
    
    Returns:
        bool: True if user is online
    """
    if not _connected_users:
        return False
    return user_id in _connected_users


def get_online_users() -> list[str]:
    """
    Get list of all currently connected user IDs.
    
    Returns:
        list: List of user IDs
    """
    if not _connected_users:
        return []
    return list(_connected_users.keys())


def get_online_count() -> int:
    """
    Get count of currently connected users.
    
    Returns:
        int: Number of online users
    """
    if not _connected_users:
        return 0
    return len(_connected_users)


# ==================== CONVENIENCE FUNCTIONS ====================

async def notify_user(user_id: str, message: str, notification_type: str = 'info') -> bool:
    """
    Send a notification to a user.
    
    Usage:
        await notify_user('user123', 'You have a new message', 'message')
    """
    return await socket_emit('notification', {
        'message': message,
        'type': notification_type
    }, user_id=user_id)


async def notify_all(message: str, notification_type: str = 'info') -> bool:
    """
    Send a notification to all users.
    
    Usage:
        await notify_all('Server will restart in 5 minutes', 'warning')
    """
    return await socket_emit('notification', {
        'message': message,
        'type': notification_type
    })


# ==================== Sever Status Emitter FUNCTIONS ====================

def get_user_by_sid(sid):
    for user_id, saved_sid in _connected_users.items():
        if saved_sid == sid:
            return user_id
    return None



async def emit_server_status(status: str, flag : Literal["INFO", "WARN", "ERROR"], sid: str) -> bool:
    """
    Emit a server status message to a specific user identified by session ID (sid).

    as ws.emit("server-status")

    Args:
        status (str): The status message to send.
        flag (str): A flag indicating the type or severity of the status.
        sid (str): The session ID of the user to whom the status should be sent.
    
    Returns:
        bool: True if the event was emitted successfully, False otherwise.
    """
    user_id = get_user_by_sid(sid)
    return await socket_emit(
        "server-status",
        {
            "flag" : flag,
            "status" : status,
            "timestamp": datetime.now(timezone.utc).isoformat()
        },
        user_id
    )