"""Connector audit logging via kernel events."""
import logging
from app.kernel.contracts.models import KernelEvent
from app.kernel.eventing.event_bus import emit_kernel_event

logger = logging.getLogger(__name__)


async def log_connector_action(
    user_id: str,
    service: str,
    action: str,
    success: bool,
    error: str = "",
) -> None:
    """Emit a kernel event for any connector action (for activity log)."""
    await emit_kernel_event(KernelEvent(
        event_type="task_completed" if success else "task_failed",
        user_id=user_id,
        tool_name=f"{service}:{action}",
        status="completed" if success else "failed",
        payload={"service": service, "action": action, "error": error},
    ))
