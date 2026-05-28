"""Action graphs - reusable step composition."""
from dataclasses import dataclass, field
from typing import Callable, Awaitable, Optional, Any
from .state_machine import FlowState
from .policies import RetryPolicy
from .events import get_event_bus, BrowserEvent, BrowserEventType


@dataclass
class StepContext:
    """Context passed to action steps."""
    page: Any
    intent: str
    ctx: dict
    runtime: Any


@dataclass
class ActionStep:
    """Single reusable action step."""
    name: str
    goal: str
    run: Callable[[StepContext], Awaitable[Any]]
    verify: Optional[Callable[[StepContext], Awaitable[bool]]] = None
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    next_state: Optional[FlowState] = None


def _result_summary(result: Any) -> dict:
    """Extract a small JSON-safe summary for the event bus."""
    if result is None:
        return {"ok": False, "summary": "none"}
    return {
        "ok": bool(getattr(result, "ok", False)),
        "confidence": float(getattr(result, "confidence", 0.0) or 0.0),
        "error_type": (
            getattr(getattr(result, "error_type", None), "value", None)
            or getattr(result, "error_type", None)
        ),
        "error_detail": getattr(result, "error_detail", None),
        "target": getattr(result, "target", None),
    }


@dataclass
class ActionGraph:
    """Ordered list of ActionSteps for a state."""
    steps: list[ActionStep]
    on_failure: Optional[Callable] = None

    async def execute(self, step_ctx: StepContext) -> Any:
        """Execute all steps in sequence, emitting per-step events."""
        bus = get_event_bus()
        results = []
        for step in self.steps:
            bus.emit(BrowserEvent(
                type=BrowserEventType.ACTION_STARTED,
                data={"step": step.name, "goal": step.goal},
            ))
            result = await step.run(step_ctx)
            results.append(result)
            bus.emit(BrowserEvent(
                type=BrowserEventType.ACTION_FINISHED,
                data={"step": step.name, **_result_summary(result)},
            ))

            # If step has verification, check it
            if step.verify:
                verified = await step.verify(step_ctx)
                if not verified and self.on_failure:
                    return await self.on_failure(step, result)

            # If step failed and no retry, abort the graph here so the
            # caller sees the *first* failure (not a later success).
            if hasattr(result, "ok") and not result.ok:
                if step.retry.retries == 0:
                    return result

        return results[-1] if results else None
