"""Event bus for browser automation."""
from enum import Enum
from typing import Any, Callable
from dataclasses import dataclass


class BrowserEventType(str, Enum):
    ACTION_STARTED = "action_started"
    ACTION_FINISHED = "action_finished"
    FLOW_STARTED = "flow_started"
    FLOW_ABORTED = "flow_aborted"
    FLOW_COMPLETED = "flow_completed"
    RECOVERY_TRIGGERED = "recovery_triggered"
    AWAITING_USER = "awaiting_user"
    PAYMENT_PAGE_REACHED = "payment_page_reached"
    BROWSER_DEAD = "browser_dead"
    TAB_CRASHED = "tab_crashed"
    # Post-payment receipt lifecycle. Emitted by receipt_watcher after a
    # PAYMENT_HANDOFF so any subscriber (UI, activity log, notifier) can
    # follow the purchase without re-implementing the polling logic.
    RECEIPT_WATCH_STARTED = "receipt_watch_started"
    RECEIPT_CAPTURED = "receipt_captured"
    RECEIPT_EMAILED = "receipt_emailed"
    RECEIPT_WATCH_TIMEOUT = "receipt_watch_timeout"
    # User closed Chrome mid-checkout — treat as an explicit cancellation
    # of the order. The watcher exits, notifications stop, no email goes
    # out. Distinct from TIMEOUT so the UI can phrase it differently.
    RECEIPT_WATCH_CANCELLED = "receipt_watch_cancelled"
    # Fired by the watcher each time the user advances through a multi-step
    # checkout (shipping → confirm → gateway → success). Lets the UI / CLI
    # show meaningful progress instead of generic "still waiting".
    CHECKOUT_STAGE_CHANGED = "checkout_stage_changed"


@dataclass
class BrowserEvent:
    type: BrowserEventType
    data: dict[str, Any]


class EventBus:
    """Simple event bus for browser automation events."""
    def __init__(self):
        self._subscribers: dict[BrowserEventType, list[Callable]] = {}

    def subscribe(self, event_type: BrowserEventType, callback: Callable):
        """Subscribe to an event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: BrowserEventType, callback: Callable) -> None:
        """Remove a previously-subscribed callback. Silently no-ops if the
        callback wasn't subscribed — callers don't have to track that.
        """
        subs = self._subscribers.get(event_type)
        if not subs:
            return
        try:
            subs.remove(callback)
        except ValueError:
            pass

    def emit(self, event: BrowserEvent):
        """Emit an event to all subscribers."""
        if event.type in self._subscribers:
            for callback in self._subscribers[event.type]:
                try:
                    callback(event)
                except Exception:
                    pass  # Don't let subscriber errors break the bus


# Global event bus instance
_event_bus = EventBus()


def get_event_bus() -> EventBus:
    """Get the global event bus."""
    return _event_bus
