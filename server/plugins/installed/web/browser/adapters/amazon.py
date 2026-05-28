"""Amazon cart adapter - first transactional adapter."""
from typing import Any
from .base import SiteAdapter, SiteCapabilities
from ..action_graph import ActionGraph, StepContext
from ..state_machine import FlowState
from .steps import (
    go_to_home, fill_search_box, submit_search, wait_for_results,
    click_first_result, add_to_cart, go_to_cart
)


class AmazonAdapter(SiteAdapter):
    """Amazon product search and add to cart."""
    
    name = "amazon"
    base_url = "https://www.amazon.com"
    capabilities = SiteCapabilities(
        supports_checkout=True,
        requires_login=False,
        high_bot_detection=False,
        supports_autofill=True,
        supports_dry_run=True
    )
    
    def __init__(self):
        super().__init__()
    
    def graph_for_state(self, state: FlowState) -> ActionGraph:
        """Return action graph for state."""
        if state == FlowState.SEARCH:
            return ActionGraph([
                go_to_home(self.base_url),
                fill_search_box("Search Amazon"),
                submit_search("Go"),
                wait_for_results(),
            ])
        
        if state == FlowState.SELECT:
            return ActionGraph([
                click_first_result("/dp/"),  # Amazon product URLs contain /dp/
            ])
        
        if state == FlowState.FORM_FILL:
            return ActionGraph([
                add_to_cart("Add to Cart"),
            ])
        
        if state == FlowState.REVIEW:
            return ActionGraph([
                go_to_cart(),
            ])
        
        return ActionGraph([])
    
    async def do_init(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        """Initialize - go to search."""
        ctx['amazon_init'] = True
        return type('Result', (), {
            'next_state': FlowState.SEARCH,
            'confidence': 1.0
        })()
    
    async def do_search(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        """Execute search graph."""
        graph = self.graph_for_state(FlowState.SEARCH)
        step_ctx = StepContext(page, intent, ctx, runtime)
        result = await graph.execute(step_ctx)
        
        ctx['amazon_search'] = True
        return type('Result', (), {
            'next_state': FlowState.SELECT,
            'confidence': result.confidence if hasattr(result, 'confidence') else 0.9
        })()
    
    async def do_select(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        """Execute select graph."""
        graph = self.graph_for_state(FlowState.SELECT)
        step_ctx = StepContext(page, intent, ctx, runtime)
        result = await graph.execute(step_ctx)
        
        ctx['amazon_select'] = True
        return type('Result', (), {
            'next_state': FlowState.FORM_FILL,
            'confidence': result.confidence if hasattr(result, 'confidence') else 0.9
        })()
    
    async def do_form_fill(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        """Add to cart."""
        graph = self.graph_for_state(FlowState.FORM_FILL)
        step_ctx = StepContext(page, intent, ctx, runtime)
        result = await graph.execute(step_ctx)
        
        ctx['amazon_add_to_cart'] = True
        return type('Result', (), {
            'next_state': FlowState.REVIEW,
            'confidence': result.confidence if hasattr(result, 'confidence') else 0.9
        })()
    
    async def do_review(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        """Go to cart."""
        graph = self.graph_for_state(FlowState.REVIEW)
        step_ctx = StepContext(page, intent, ctx, runtime)
        result = await graph.execute(step_ctx)
        
        ctx['amazon_cart'] = True
        return type('Result', (), {
            'next_state': FlowState.USER_CONFIRM,
            'confidence': result.confidence if hasattr(result, 'confidence') else 0.9
        })()
    
    async def do_user_confirm(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        """Request user confirmation before checkout."""
        from ..human_loop import request_user_confirmation
        
        confirmed = await request_user_confirmation(
            "Ready to proceed to checkout?",
            {"url": page.url, "cart_items": "1+"}
        )
        
        if confirmed:
            return type('Result', (), {
                'next_state': FlowState.PAYMENT_HANDOFF,
                'confidence': 1.0
            })()
        else:
            return type('Result', (), {
                'next_state': FlowState.ABORTED,
                'confidence': 0.0
            })()
    
    async def verify_goal_completed(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        """Verify item is in cart."""
        from ..verification import GoalVerifier
        
        if not self.verifier:
            self.verifier = GoalVerifier()
        
        # Check URL contains /cart
        cart_url = await self.verifier.url_contains(page, "/cart")
        
        # Check cart has items
        cart_text = await self.verifier.text_appears(page, "Subtotal")
        
        if cart_url and cart_text:
            return type('Result', (), {
                'next_state': FlowState.DONE,
                'confidence': 1.0
            })()
        elif cart_url:
            return type('Result', (), {
                'next_state': FlowState.DONE,
                'confidence': 0.8
            })()
        else:
            return type('Result', (), {
                'next_state': FlowState.ABORTED,
                'confidence': 0.0
            })()
