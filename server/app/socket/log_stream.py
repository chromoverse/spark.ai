"""
Real-time log streaming via WebSocket.

Subscribes to the kernel event bus and forwards events to connected
clients as 'spark:log' events for live execution timeline display.
Also emits additional lifecycle events for richer real-time visibility.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.kernel.contracts.models import KernelEvent
from app.kernel.eventing.event_bus import get_kernel_event_bus
from app.socket.utils import socket_emit

logger = logging.getLogger(__name__)

_registered = False


async def _forward_event_to_client(event: KernelEvent) -> None:
    """Forward kernel events to the owning user's socket as spark:log."""
    if not event.user_id:
        return
    await socket_emit(
        "spark:log",
        event.to_dict(),
        user_id=event.user_id,
    )


async def emit_spark_log(user_id: str, event_type: str, **kwargs) -> None:
    """Convenience helper to emit a spark:log event directly."""
    if not user_id:
        return
    payload = {
        "event_type": event_type,
        "user_id": user_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **kwargs,
    }
    await socket_emit("spark:log", payload, user_id=user_id)


def register_log_stream() -> None:
    """Subscribe to kernel event bus once at startup."""
    global _registered
    if _registered:
        return
    get_kernel_event_bus().subscribe(_forward_event_to_client)
    _registered = True
    logger.info("Real-time log stream registered on kernel event bus")
