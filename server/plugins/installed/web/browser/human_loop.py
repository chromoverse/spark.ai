"""Human-in-the-loop confirmation flows."""
import asyncio
from typing import Any, Optional, Callable
from .events import get_event_bus, BrowserEvent, BrowserEventType


async def request_user_confirmation(
    message: str,
    evidence: dict,
    *,
    timeout_s: float = 300.0
) -> bool:
    """Request user confirmation (blocks until response or timeout)."""
    bus = get_event_bus()
    
    # Emit awaiting user event
    bus.emit(BrowserEvent(
        type=BrowserEventType.AWAITING_USER,
        data={"message": message, "evidence": evidence}
    ))
    
    # In a real implementation, this would wait for socket/UI response
    # For now, stub returns True after brief wait
    await asyncio.sleep(2.0)
    return True


async def pause_for_human(
    page: Any,
    *,
    reason: str,
    predicate: Optional[Callable] = None,
    timeout_s: float = 120.0,
    reminder_every_s: float = 5.0,
    message: Optional[str] = None,
    extra: Optional[dict] = None,
) -> bool:
    """Pause and wait for a human to complete an action.

    Returns True if the predicate eventually passes (i.e. the human
    handled it); False if it didn't pass within timeout_s OR if there is
    no predicate to observe.

    Two behaviors callers should know:

    * Periodic reminders. We re-emit ``AWAITING_USER`` every
      ``reminder_every_s`` seconds with a ``remaining_s`` countdown so a
      UI / notifier can keep nudging the user without each subsystem
      writing its own timer. Set ``reminder_every_s`` to 0 to disable.

    * No predicate ⇒ we cannot observe the human's progress ⇒ return False
      immediately so the caller can decide (typically: re-check the signal
      and abort if it persists). This prevents the previous bug where a
      bare ``pause_for_human`` slept 30s and returned True unconditionally,
      hiding every false-positive captcha detection.
    """
    bus = get_event_bus()
    extra = extra or {}

    def _emit(remaining: float, *, is_reminder: bool) -> None:
        bus.emit(BrowserEvent(
            type=BrowserEventType.AWAITING_USER,
            data={
                "reason": reason,
                "url": getattr(page, "url", None),
                "message": message or f"Human intervention needed: {reason}",
                "timeout_s": timeout_s,
                "remaining_s": max(0.0, remaining),
                "reminder": is_reminder,
                **extra,
            },
        ))

    # Initial prompt — fires immediately so any listener can show UI
    # before we start polling.
    _emit(timeout_s, is_reminder=False)

    if predicate is None:
        return False

    start = asyncio.get_event_loop().time()
    last_reminder = start
    while True:
        now = asyncio.get_event_loop().time()
        elapsed = now - start
        if elapsed >= timeout_s:
            return False

        # Reminder every N seconds (default 5). Skip on the first tick
        # since we just emitted the initial prompt above.
        if reminder_every_s > 0 and (now - last_reminder) >= reminder_every_s:
            _emit(timeout_s - elapsed, is_reminder=True)
            last_reminder = now

        try:
            if await predicate(page):
                return True
        except Exception:
            pass
        await asyncio.sleep(1.0)
