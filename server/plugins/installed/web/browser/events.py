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
