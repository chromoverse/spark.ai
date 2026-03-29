"""
core/state.py

Finite State Machine for the voice daemon.

States:
  IDLE       — mic open, listening for wake word only
  WAKE       — wake word detected, ding.wav playing
  LISTENING  — ding done, VAD now active, waiting for speech to start
  STREAMING  — speech detected, sending PCM chunks to server
  PROCESSING — user-stop-speaking sent, waiting for server to respond
               (blocks new wake word triggers while in-flight)

Transitions are the ONLY place state changes. No other module sets _state directly.
All other modules call transition() and read current().
"""

import asyncio
import logging
from enum import Enum, auto
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)


class State(Enum):
    IDLE       = auto()
    WAKE       = auto()
    LISTENING  = auto()
    STREAMING  = auto()
    PROCESSING = auto()


# Valid transitions — (from, to)
_ALLOWED: set[tuple[State, State]] = {
    (State.IDLE,       State.WAKE),
    (State.WAKE,       State.LISTENING),
    (State.WAKE,       State.IDLE),       # ding failed / interrupted
    (State.LISTENING,  State.STREAMING),
    (State.LISTENING,  State.IDLE),       # silence timeout with no speech
    (State.STREAMING,  State.PROCESSING),
    (State.STREAMING,  State.IDLE),       # socket dropped mid-stream
    (State.PROCESSING, State.IDLE),       # server responded or timed out
}

StateChangeCallback = Callable[[State, State], Awaitable[None]]


class DaemonFSM:
    def __init__(self) -> None:
        self._state = State.IDLE
        self._lock = asyncio.Lock()
        self._callbacks: list[StateChangeCallback] = []

    def current(self) -> State:
        return self._state

    def is_idle(self) -> bool:
        return self._state == State.IDLE

    def is_busy(self) -> bool:
        """True whenever the daemon should NOT respond to a new wake word."""
        return self._state in (State.STREAMING, State.PROCESSING)

    def on_change(self, cb: StateChangeCallback) -> None:
        """Register an async callback fired on every state transition."""
        self._callbacks.append(cb)

    async def transition(self, to: State) -> bool:
        """
        Attempt a state transition.
        Returns True if the transition happened, False if it was rejected.
        """
        async with self._lock:
            frm = self._state
            if (frm, to) not in _ALLOWED:
                logger.warning(
                    f"🚫 Invalid transition {frm.name} → {to.name} (ignored)"
                )
                return False

            self._state = to
            logger.debug(f"🔄 State: {frm.name} → {to.name}")

        # Fire callbacks outside the lock so they can themselves call transition()
        for cb in self._callbacks:
            try:
                await cb(frm, to)
            except Exception as exc:
                logger.error(f"❌ State callback error: {exc}")

        return True

    async def reset(self) -> None:
        """Force back to IDLE — for crash recovery only."""
        async with self._lock:
            prev = self._state
            self._state = State.IDLE
        logger.warning(f"⚠️ Force-reset from {prev.name} → IDLE")


# Module-level singleton — import this everywhere
fsm = DaemonFSM()