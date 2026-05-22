import asyncio
import logging
from typing import Set

logger = logging.getLogger(__name__)

class CancellationContext:
    """
    Context carrying cancellation status for task execution.
    Can trigger callbacks when cancelled (e.g. killing process tree).
    """
    def __init__(self):
        self._is_cancelled = False
        self._callbacks = set()

    @property
    def is_cancelled(self) -> bool:
        return self._is_cancelled

    def cancel(self):
        """Trigger cancellation and execute all registered callbacks."""
        if self._is_cancelled:
            return
        self._is_cancelled = True
        logger.info("CancellationContext: cancellation triggered")
        for cb in list(self._callbacks):
            try:
                cb()
            except Exception as e:
                logger.error("Error in cancellation callback: %s", e)

    def register_callback(self, callback):
        """Register a callback to run on cancel (e.g. proc.terminate)."""
        if self._is_cancelled:
            callback()
        else:
            self._callbacks.add(callback)

    def unregister_callback(self, callback):
        self._callbacks.discard(callback)
