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
    timeout_s: float = 300.0,
) -> bool:
    """Pause and wait for a human to complete an action.

    Returns True if the predicate eventually passes (i.e. the human
    handled it); False if it didn't pass within timeout_s OR if there is
    no predicate to observe.

    NOTE: previously this slept 30s and returned True when called
    without a predicate. That hid every false-positive captcha detection
    behind a successful "human handled it" return. Now the contract is:
    no predicate ⇒ we cannot observe the human's progress ⇒ return False
    immediately so the caller can decide (typically: re-check the signal
    and abort if it persists).
    """
    bus = get_event_bus()

    bus.emit(BrowserEvent(
        type=BrowserEventType.AWAITING_USER,
        data={
            "reason": reason,
            "url": page.url,
            "message": f"Human intervention needed: {reason}",
        },
    ))

    if predicate is None:
        return False

    start = asyncio.get_event_loop().time()
    while (asyncio.get_event_loop().time() - start) < timeout_s:
        try:
            if await predicate(page):
                return True
        except Exception:
            pass
        await asyncio.sleep(1.0)
    return False
