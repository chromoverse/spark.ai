"""
Socket Server - Core Socket.IO instance and connection lifecycle.

This module creates the Socket.IO server and handles 
connect/disconnect events with JWT authentication.
"""

import os
import socketio
import logging
from typing import Dict, Set

from app.jwt import config as jwt
from app.kernel.execution.approval_coordinator import get_approval_coordinator

logger = logging.getLogger(__name__)

# ==================== SOCKET.IO INSTANCE ====================

# Quieter loggers — suppress the massive base64 audio payloads
_sio_logger = logging.getLogger("socketio")
_sio_logger.setLevel(logging.WARNING)
_eio_logger = logging.getLogger("engineio")
_eio_logger.setLevel(logging.WARNING)

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
    logger=_sio_logger,
    engineio_logger=_eio_logger,
    namespaces=["/"],
    ping_timeout=60,
    ping_interval=25,
)

socket_app = socketio.ASGIApp(sio)

# Support multiple connections per user (multi-tab / multi-device)
connected_users: Dict[str, Set[str]] = {}  # user_id → set of sids


# ==================== CONNECTION LIFECYCLE ====================

@sio.event
async def connect(sid, environ, auth):
    """
    Authenticate with JWT on connect and save user_id to session.
    """
    auth = auth or {}
    token = auth.get("token", None)
    client_type = str(auth.get("client_type", "user")).strip().lower()

    if client_type == "daemon":
        daemon_service_token = os.environ.get("DAEMON_SERVICE_TOKEN", "").strip()
        if not daemon_service_token:
            logger.error("❌ Daemon connection rejected: DAEMON_SERVICE_TOKEN is not configured")
            raise ConnectionRefusedError("Daemon auth is not configured")

        if token != daemon_service_token:
            logger.warning("⚠️ Invalid daemon token provided by client")
            raise ConnectionRefusedError("Invalid daemon auth token")

        await sio.save_session(sid, {
            "user_id": "__daemon__",
            "client_type": "daemon",
            "authenticated": True,
        })
        logger.info("🤖 Daemon connected with sid %s", sid)
        return True

    if not token:
        logger.warning(f"⚠️ No token provided by client")
        raise ConnectionRefusedError("Missing auth token")

    try:
        jwt_payload = jwt.decode_token(token)
        user_id = jwt_payload.get("sub")

        if not user_id:
            logger.warning(f"⚠️ Invalid token provided by client")
            raise ConnectionRefusedError("Invalid auth token")

        # Save user_id to socket session
        await sio.save_session(sid, {
            "user_id": user_id,
            "client_type": "user",
            "authenticated": True
        })

        # Track multiple connections per user
        if user_id not in connected_users:
            connected_users[user_id] = set()
        connected_users[user_id].add(sid)

        logger.info(
            f"🟢 User {user_id} connected with sid {sid} "
            f"(total connections: {len(connected_users[user_id])})"
        )
        return True

    except Exception as e:
        logger.error(f"❌ Authentication error: {e}")
        raise ConnectionRefusedError("Authentication failed")


@sio.event
async def disconnect(sid):
    """
    Clean up connection tracking on disconnect.
    """
    try:
        session = await sio.get_session(sid)
        user_id = session.get("user_id")
        client_type = session.get("client_type")

        if user_id and user_id in connected_users:
            connected_users[user_id].discard(sid)

            if not connected_users[user_id]:
                del connected_users[user_id]
                get_approval_coordinator().cancel_user_requests(user_id)
                logger.info(f"👋 User {user_id} fully disconnected (no active connections)")
            else:
                logger.info(
                    f"🔌 User {user_id} disconnected sid {sid} "
                    f"({len(connected_users[user_id])} connections remaining)"
                )
        elif client_type == "daemon":
            logger.info("🤖 Daemon disconnected sid %s", sid)
        else:
            logger.info(f"🔌 Client {sid} disconnected (no user session)")

    except Exception as e:
        logger.error(f"❌ Error during disconnect cleanup: {e}")


@sio.event
async def register_user(sid, user_id):
    """
    ⚠️ DEPRECATED — User registration now happens automatically during connect.
    Kept for backward compatibility.
    """
    session = await sio.get_session(sid)
    actual_user_id = session.get("user_id")
    logger.info(
        f"ℹ️ Received deprecated register_user event from {sid} "
        f"(user already authenticated as {actual_user_id})"
    )
    await sio.emit("registered", {"userId": actual_user_id}, to=sid)
