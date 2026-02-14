"""
Socket Module — Initialize once, use anywhere.

Usage in main.py:
    from app.socket import init_socket, sio, socket_app, connected_users
    init_socket()          # registers all event handlers
    app.mount("/socket.io", socket_app)

Usage anywhere else:
    from app.socket.utils import socket_emit, emit_server_status
    from app.socket.user_utils import get_user_from_session, send_to_user
"""

from app.socket.server import sio, socket_app, connected_users

# Re-export core objects for convenience
__all__ = [
    "init_socket",
    "sio",
    "socket_app",
    "connected_users",
]


def init_socket():
    """
    One-time initialization — call in main.py lifespan.
    Registers all socket event handlers (chat, TTS, tasks).
    """
    import logging
    logger = logging.getLogger(__name__)

    # Register chat event handlers (text + voice query)
    from app.socket.chat_utils import register_chat_events
    register_chat_events()

    logger.info("✅ Socket module fully initialized")
