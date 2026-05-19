"""ExternalActionBridge — unified interface for external service actions."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Awaitable, Dict, Optional

from app.features.bridge.rate_limiter import RateLimiter
from app.features.external_service.token_manager import get_valid_access_token
from app.kernel.contracts.models import KernelEvent
from app.kernel.eventing.event_bus import emit_kernel_event

logger = logging.getLogger(__name__)


@dataclass
class ExternalActionResult:
    success: bool
    data: Dict[str, Any]
    error: str = ""


class ExternalActionBridge:
    """Unified interface for tools that interact with external services."""

    def __init__(self):
        self.rate_limiter = RateLimiter()

    async def execute(
        self,
        service: str,
        action: str,
        user_id: str,
        handler: Callable[..., Awaitable[Dict[str, Any]]],
        **kwargs: Any,
    ) -> ExternalActionResult:
        """Execute an external action with rate limiting, token check, and audit.

        Args:
            service: e.g. "gmail", "google_calendar"
            action: e.g. "read_emails", "send_email"
            user_id: current user
            handler: async callable that performs the actual work, returns data dict
            **kwargs: passed to handler
        """
        # 1. Rate limit
        if not self.rate_limiter.allow(service, user_id):
            return ExternalActionResult(success=False, data={}, error="Rate limited — try again shortly")

        # 2. Token check
        try:
            token = await get_valid_access_token(user_id, service)
            if not token:
                return ExternalActionResult(
                    success=False, data={},
                    error=f"Not authenticated with {service}. Please connect your account.",
                )
        except Exception as exc:
            return ExternalActionResult(success=False, data={}, error=str(exc))

        # 3. Execute
        try:
            data = await handler(**kwargs)
            success = True
            error = ""
        except Exception as exc:
            logger.error("Bridge action %s:%s failed: %s", service, action, exc)
            data = {}
            success = False
            error = str(exc)

        # 4. Audit log via kernel event
        await emit_kernel_event(KernelEvent(
            event_type="task_completed" if success else "task_failed",
            user_id=user_id,
            tool_name=f"{service}:{action}",
            status="completed" if success else "failed",
            payload={"service": service, "action": action, "error": error},
        ))

        return ExternalActionResult(success=success, data=data, error=error)


_instance: Optional[ExternalActionBridge] = None


def get_action_bridge() -> ExternalActionBridge:
    global _instance
    if _instance is None:
        _instance = ExternalActionBridge()
    return _instance
