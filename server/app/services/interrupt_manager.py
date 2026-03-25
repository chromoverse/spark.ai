"""
Interrupt Manager — per-user cancellation flag for TTS/streaming.

Usage:
    from app.services.interrupt_manager import get_interrupt_manager

    mgr = get_interrupt_manager()
    mgr.set(user_id)        # signal interrupt
    mgr.is_set(user_id)     # check (zero-cost if not set)
    mgr.clear(user_id)      # reset before new request
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class InterruptManager:
    """Lightweight per-user interrupt flag using asyncio.Event."""

    def __init__(self) -> None:
        self._flags: Dict[str, asyncio.Event] = {}

    def set(self, user_id: str) -> None:
        """Signal an interrupt for the given user."""
        if user_id not in self._flags:
            self._flags[user_id] = asyncio.Event()
        self._flags[user_id].set()
        logger.info("🛑 Interrupt set for user=%s", user_id)

    def clear(self, user_id: str) -> None:
        """Reset the interrupt flag (call before starting a new request)."""
        self._flags[user_id] = asyncio.Event()  # fresh unset event

    def is_set(self, user_id: str) -> bool:
        """Fast check — returns False if no flag exists (zero overhead for normal flow)."""
        flag = self._flags.get(user_id)
        return flag is not None and flag.is_set()

    def cleanup(self, user_id: str) -> None:
        """Remove all state for a disconnected user."""
        self._flags.pop(user_id, None)


# ── Singleton ──────────────────────────────────────────────────────────────────

_instance: Optional[InterruptManager] = None


def get_interrupt_manager() -> InterruptManager:
    global _instance
    if _instance is None:
        _instance = InterruptManager()
    return _instance
