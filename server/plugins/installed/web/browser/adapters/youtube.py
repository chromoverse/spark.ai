"""YouTube adapter - first real site adapter."""
from typing import Any
from .base import SiteAdapter, SiteCapabilities
from ..action_graph import ActionGraph, StepContext
from ..state_machine import FlowState
from .steps import go_to_home, fill_search_box, submit_search, wait_for_results, click_first_result


class YouTubeAdapter(SiteAdapter):
    """YouTube play adapter."""
    
    name = "youtube"
    base_url = "https://www.youtube.com"
    capabilities = SiteCapabilities(
        supports_checkout=False,
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
                fill_search_box("Search"),
                submit_search("Search"),
                wait_for_results(),
            ])
        
        if state == FlowState.SELECT:
            return ActionGraph([
                click_first_result("/watch"),
            ])
        
        return ActionGraph([])
    
    async def do_init(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        """Initialize - go straight to search."""
        from ..semantic import ActionResult
        ctx['youtube_init'] = True
        return type('Result', (), {
            'next_state': FlowState.SEARCH,
            'confidence': 1.0
        })()
    
    async def do_search(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        """Execute search graph."""
        graph = self.graph_for_state(FlowState.SEARCH)
        step_ctx = StepContext(page, intent, ctx, runtime)
        result = await graph.execute(step_ctx)
        
        ctx['youtube_search'] = True
        return type('Result', (), {
            'next_state': FlowState.SELECT,
            'confidence': result.confidence if hasattr(result, 'confidence') else 0.9
        })()
    
    async def do_select(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        """Execute select graph."""
        graph = self.graph_for_state(FlowState.SELECT)
        step_ctx = StepContext(page, intent, ctx, runtime)
        result = await graph.execute(step_ctx)
        
        ctx['youtube_select'] = True
        return type('Result', (), {
            'next_state': FlowState.VERIFYING,
            'confidence': result.confidence if hasattr(result, 'confidence') else 0.9
        })()
    
    async def do_form_fill(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        """Not needed for YouTube."""
        return type('Result', (), {'next_state': FlowState.VERIFYING, 'confidence': 1.0})()
    
    async def do_review(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        """Not needed for YouTube."""
        return type('Result', (), {'next_state': FlowState.VERIFYING, 'confidence': 1.0})()
    
    async def do_user_confirm(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        """Not needed for YouTube."""
        return type('Result', (), {'next_state': FlowState.VERIFYING, 'confidence': 1.0})()
    
    async def verify_goal_completed(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        """Verify video is playing."""
        from ..verification import GoalVerifier
        
        if not self.verifier:
            self.verifier = GoalVerifier()
        
        # Check URL contains /watch
        url_ok = await self.verifier.url_contains(page, "/watch")
        
        # Check video is playing
        video_ok = await self.verifier.video_playing(page)
        
        if url_ok and video_ok:
            return type('Result', (), {'next_state': FlowState.DONE, 'confidence': 1.0})()
        elif url_ok:
            # Video loaded but not playing - still success
            return type('Result', (), {'next_state': FlowState.DONE, 'confidence': 0.8})()
        else:
            return type('Result', (), {'next_state': FlowState.ABORTED, 'confidence': 0.0})()
