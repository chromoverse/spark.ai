"""Flow state machine with budgets and verification."""
import asyncio
from enum import Enum
from dataclasses import dataclass
from typing import Any, Optional, Callable
from .errors import BrowserError, BrowserErrorType
from .policies import MAX_FLOW_DURATION_S, MAX_ACTIONS_PER_FLOW, CircuitBreaker
from .recovery import RecoveryEngine
from .intelligence import classify_page, PageIntent, detect_captcha
from .human_loop import pause_for_human
from .events import get_event_bus, BrowserEvent, BrowserEventType


class FlowState(str, Enum):
    INIT = "init"
    SEARCH = "search"
    SELECT = "select"
    FORM_FILL = "form_fill"
    REVIEW = "review"
    USER_CONFIRM = "user_confirm"
    PAYMENT_HANDOFF = "payment_handoff"
    VERIFYING = "verifying"
    DONE = "done"
    ABORTED = "aborted"


@dataclass
class FlowBudget:
    max_duration_s: float
    max_actions: int
    start_time: float = 0.0
    action_count: int = 0
    
    def start(self):
        self.start_time = asyncio.get_event_loop().time()
    
    def exhausted(self) -> bool:
        elapsed = asyncio.get_event_loop().time() - self.start_time
        return elapsed >= self.max_duration_s or self.action_count >= self.max_actions
    
    def record_action(self):
        self.action_count += 1


@dataclass
class FlowResult:
    success: bool
    state: FlowState
    data: dict
    error: Optional[BrowserError] = None


class Flow:
    """State machine for browser automation flows."""
    
    def __init__(
        self,
        adapter: Any,
        intent: str,
        run_id: str,
        page: Any,
        runtime: Any,
        *,
        approve_payment: bool = False,
    ):
        self.adapter = adapter
        self.intent = intent
        self.run_id = run_id
        self.page = page
        self.runtime = runtime
        self.approve_payment = approve_payment

        self.state = FlowState.INIT
        self.budget = FlowBudget(MAX_FLOW_DURATION_S, MAX_ACTIONS_PER_FLOW)
        self.breaker = CircuitBreaker()
        self.recovery = RecoveryEngine()
        self.bus = get_event_bus()

        self._context: dict = {}
        self._aborted_emitted: bool = False
    
    async def run(self) -> FlowResult:
        """Execute the flow."""
        self.budget.start()
        
        self.bus.emit(BrowserEvent(
            type=BrowserEventType.FLOW_STARTED,
            data={"run_id": self.run_id, "intent": self.intent}
        ))
        
        try:
            terminal = (FlowState.DONE, FlowState.ABORTED, FlowState.PAYMENT_HANDOFF)
            while not self.budget.exhausted() and self.state not in terminal:
                await self._pre_step()

                if self.state in terminal:
                    break

                result = await self._dispatch_state()
                await self._post_step(result)

            if self.budget.exhausted():
                return self._abort(BrowserErrorType.BUDGET_EXCEEDED, "Flow budget exhausted")

            if self.state == FlowState.PAYMENT_HANDOFF:
                # Hard stop. We never submit a payment form. Whether the
                # flow counts as a success depends on whether the caller
                # opted in to reaching this state via approve_payment.
                self._context["payment_handoff"] = True
                self._context["url"] = self.page.url
                return FlowResult(self.approve_payment, self.state, self._context)

            if self.state == FlowState.DONE:
                self.bus.emit(BrowserEvent(
                    type=BrowserEventType.FLOW_COMPLETED,
                    data={"run_id": self.run_id, "state": self.state.value}
                ))
                return FlowResult(True, self.state, self._context)

            if self.state == FlowState.ABORTED:
                # A handler (e.g. adapter.verify_goal_completed) flipped
                # state to ABORTED directly via _post_step's transition.
                # FLOW_ABORTED may not have fired — emit it once so the
                # event trail is honest, but DON'T re-call _abort: that
                # would overwrite whatever reason got us here.
                if not self._aborted_emitted:
                    self.bus.emit(BrowserEvent(
                        type=BrowserEventType.FLOW_ABORTED,
                        data={
                            "run_id": self.run_id,
                            "error_type": "transitioned_to_aborted",
                            "detail": "handler returned next_state=ABORTED",
                        },
                    ))
                    self._aborted_emitted = True
                return FlowResult(False, self.state, self._context)

            # Loop ended without DONE / ABORTED / PAYMENT_HANDOFF / budget.
            # Don't exit silently — surface it as an abort so subscribers
            # (and tests) can see the flow actually terminated.
            return self._abort(
                BrowserErrorType.GOAL_UNVERIFIED,
                f"Flow exited in non-terminal state {self.state.value}",
            )
            
        except Exception as e:
            return self._abort(BrowserErrorType.TIMEOUT, str(e))
    
    async def _pre_step(self):
        """Pre-step checks."""
        if self.budget.exhausted():
            self._abort(BrowserErrorType.BUDGET_EXCEEDED, "Budget exhausted")
            return
        
        if self.breaker.tripped:
            self._abort(BrowserErrorType.CIRCUIT_BREAKER, "Circuit breaker tripped")
            return
        
        # Check for CAPTCHA. We pass a predicate that resolves once the
        # captcha widget is gone, so the human-loop only returns True
        # when the user actually solved it. If we time out (or no human
        # responder is wired), abort cleanly with a typed error rather
        # than continuing into a broken flow.
        if await detect_captcha(self.page):
            async def _captcha_cleared(p):
                return not await detect_captcha(p)
            cleared = await pause_for_human(
                self.page, reason="captcha", predicate=_captcha_cleared,
                timeout_s=120.0,
            )
            if not cleared:
                self._abort(BrowserErrorType.CAPTCHA, "Captcha not solved")
                return

        # Verify page intent matches expected state
        page_intent = await classify_page(self.page)
        if page_intent == PageIntent.LOGIN and self.state != FlowState.INIT:
            error = BrowserError(BrowserErrorType.LOGIN_REQUIRED, "Login required")
            await self.recovery.attempt(self.page, error, {"state": self.state.value}, self.runtime)
    
    async def _dispatch_state(self) -> Any:
        """Dispatch to adapter's state handler."""
        self.budget.record_action()
        
        handler_map = {
            FlowState.INIT: self.adapter.do_init,
            FlowState.SEARCH: self.adapter.do_search,
            FlowState.SELECT: self.adapter.do_select,
            FlowState.FORM_FILL: self.adapter.do_form_fill,
            FlowState.REVIEW: self.adapter.do_review,
            FlowState.USER_CONFIRM: self.adapter.do_user_confirm,
            FlowState.VERIFYING: self.adapter.verify_goal_completed,
        }
        
        handler = handler_map.get(self.state)
        if handler:
            return await handler(self.page, self.intent, self._context, self.runtime)
        
        return None
    
    async def _post_step(self, result: Any):
        """Post-step processing."""
        if not result:
            return
        
        # Record confidence for circuit breaker
        if hasattr(result, 'confidence'):
            self.breaker.record(result.confidence)
        
        # Handle state transitions
        if hasattr(result, 'next_state'):
            self._validate_transition(result.next_state)
            self.state = result.next_state
        
        # Check for payment page. We always emit + transition to
        # PAYMENT_HANDOFF (which is terminal). The approve_payment flag
        # governs whether reaching this state counts as success — it
        # NEVER means "submit the form." That guarantee lives here, not
        # in any adapter.
        from .intelligence import detect_payment_page
        if await detect_payment_page(self.page):
            self.bus.emit(BrowserEvent(
                type=BrowserEventType.PAYMENT_PAGE_REACHED,
                data={"url": self.page.url, "approved": self.approve_payment},
            ))
            if not self.approve_payment:
                self._abort(
                    BrowserErrorType.PAYMENT_BLOCKED,
                    "Reached payment page without approve_payment=True",
                )
                return
            self.state = FlowState.PAYMENT_HANDOFF
    
    def _validate_transition(self, next_state: FlowState):
        """Validate state transition is legal."""
        valid_transitions = {
            FlowState.INIT: [FlowState.SEARCH, FlowState.DONE],
            FlowState.SEARCH: [FlowState.SELECT, FlowState.DONE],
            FlowState.SELECT: [FlowState.FORM_FILL, FlowState.DONE, FlowState.VERIFYING],
            FlowState.FORM_FILL: [FlowState.REVIEW, FlowState.VERIFYING],
            FlowState.REVIEW: [FlowState.USER_CONFIRM, FlowState.VERIFYING],
            FlowState.USER_CONFIRM: [FlowState.PAYMENT_HANDOFF, FlowState.VERIFYING],
            FlowState.VERIFYING: [FlowState.DONE, FlowState.ABORTED],
        }
        
        allowed = valid_transitions.get(self.state, [])
        if next_state not in allowed:
            raise ValueError(f"Invalid transition: {self.state} -> {next_state}")
    
    def _abort(self, error_type: BrowserErrorType, detail: str) -> FlowResult:
        """Abort the flow."""
        self.state = FlowState.ABORTED
        error = BrowserError(error_type, detail, self.page.url)

        self.bus.emit(BrowserEvent(
            type=BrowserEventType.FLOW_ABORTED,
            data={
                "run_id": self.run_id,
                "error_type": error_type.value,
                "detail": detail,
            },
        ))
        self._aborted_emitted = True

        return FlowResult(False, self.state, self._context, error)
