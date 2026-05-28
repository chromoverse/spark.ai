"""Toy adapter for testing Layer 2."""
from dataclasses import dataclass
from typing import Any
from .base import SiteAdapter, SiteCapabilities
from ..state_machine import FlowState
from ..semantic import goto, click_by_text, fill_form


@dataclass
class ToyResult:
    next_state: FlowState
    confidence: float = 0.9


class ToyAdapter(SiteAdapter):
    """Simple adapter for testing with static HTML."""
    
    name = "toy"
    base_url = "file://"
    capabilities = SiteCapabilities(
        supports_checkout=False,
        requires_login=False,
        high_bot_detection=False,
        supports_autofill=True,
        supports_dry_run=True
    )
    
    def __init__(self, test_file: str):
        super().__init__()
        self.test_file = test_file
    
    async def do_init(self, page: Any, intent: str, ctx: dict, runtime: Any) -> ToyResult:
        """Navigate to test file."""
        result = await goto(page, f"file:///{self.test_file}", runtime)
        ctx['init_done'] = True
        return ToyResult(FlowState.SEARCH, result.confidence)
    
    async def do_search(self, page: Any, intent: str, ctx: dict, runtime: Any) -> ToyResult:
        """Fill search form."""
        result = await fill_form(page, {"search": intent}, runtime)
        ctx['search_done'] = True
        return ToyResult(FlowState.SELECT, result.confidence)
    
    async def do_select(self, page: Any, intent: str, ctx: dict, runtime: Any) -> ToyResult:
        """Click submit button."""
        result = await click_by_text(page, "Submit", runtime)
        ctx['select_done'] = True
        return ToyResult(FlowState.VERIFYING, result.confidence)
    
    async def do_form_fill(self, page: Any, intent: str, ctx: dict, runtime: Any) -> ToyResult:
        return ToyResult(FlowState.VERIFYING)
    
    async def do_review(self, page: Any, intent: str, ctx: dict, runtime: Any) -> ToyResult:
        return ToyResult(FlowState.VERIFYING)
    
    async def do_user_confirm(self, page: Any, intent: str, ctx: dict, runtime: Any) -> ToyResult:
        return ToyResult(FlowState.VERIFYING)
    
    async def verify_goal_completed(self, page: Any, intent: str, ctx: dict, runtime: Any) -> ToyResult:
        """Verify all steps completed."""
        if ctx.get('init_done') and ctx.get('search_done') and ctx.get('select_done'):
            return ToyResult(FlowState.DONE, 1.0)
        return ToyResult(FlowState.ABORTED, 0.0)
