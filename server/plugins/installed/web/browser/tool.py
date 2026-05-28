"""BrowserAgentTool - LLM interface for browser automation."""
import logging
from typing import Any, Dict
from pathlib import Path
from app.plugins.tools.tool_base import BaseTool, ToolOutput
from .runtime.playwright import PlaywrightRuntime
from .session import get_browser_session
from .state_machine import Flow
from .replay_log import ReplayLog
from .verification import GoalVerifier
from .errors import BrowserErrorType

logger = logging.getLogger(__name__)

# Adapter registry
_ADAPTERS: Dict[str, Any] = {}

# Forbidden intents
FORBIDDEN_INTENTS = {
    "bank_transfer",
    "crypto_send",
    "delete_account",
    "wire_money",
    "close_account",
}


def register_adapter(intent: str, adapter_class: Any):
    """Register an adapter for an intent."""
    _ADAPTERS[intent] = adapter_class


class BrowserAgentTool(BaseTool):
    """Automated browser agent for transactional flows."""
    
    TOOL_DESCRIPTION = (
        "Automated browser agent that can perform complex transactional flows: "
        "play videos on YouTube, book hotels, buy products, reserve tables. "
        "Uses the user's existing browser session (CDP attach) so login state "
        "is preserved. Supports dry-run mode for safe testing."
    )
    
    EXECUTION_TARGET = "server"
    
    PARAMS_SCHEMA: Dict[str, Any] = {
        "intent": {
            "type": "string",
            "required": True,
            "description": "What to do: 'youtube_play', 'book_hotel', 'buy_product', etc."
        },
        "query": {
            "type": "string",
            "required": False,
            "description": "Search query or item name"
        },
        "entity": {
            "type": "object",
            "required": False,
            "description": "Structured entity from web_research"
        },
        "approve_payment": {
            "type": "boolean",
            "default": False,
            "description": "Whether to proceed to payment (always stops before submitting)"
        },
        "dry_run": {
            "type": "boolean",
            "default": False,
            "description": "Dry-run mode: highlights elements without clicking"
        },
        "params": {
            "type": "object",
            "required": False,
            "description": "Adapter-specific options such as dates, guests, rooms, or handoff timeout"
        },
    }
    
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {
            "intent": {"type": "string"},
            "state": {"type": "string"},
            "automated": {"type": "boolean"},
            "message": {"type": "string"},
            "context": {"type": "object", "optional": True},
        },
        "error": {"type": "string"},
    }
    
    EXAMPLES = [
        {"user_utterance": "play lofi beats on youtube"},
        {"user_utterance": "book that hotel we found"},
    ]
    
    SEMANTIC_TAGS = ["browser", "automation", "youtube", "booking", "purchase"]
    TOOL_CATEGORY = "browser_agent"
    
    def get_tool_name(self) -> str:
        return "browser_agent"
    
    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        intent = str(self.get_input(inputs, "intent", "")).strip().lower()
        
        # Check forbidden intents
        if intent in FORBIDDEN_INTENTS:
            return ToolOutput(
                success=False,
                data={"intent": intent},
                error=f"Forbidden intent: {intent}"
            )
        
        # Look up adapter
        adapter_class = _ADAPTERS.get(intent)
        if not adapter_class:
            return ToolOutput(
                success=False,
                data={"intent": intent},
                error=f"No adapter registered for intent: {intent}. Available: {list(_ADAPTERS.keys())}"
            )
        
        # Get query
        query = self.get_input(inputs, "query", "")
        if not query and self.get_input(inputs, "entity"):
            entity = self.get_input(inputs, "entity")
            query = entity.get("name") or entity.get("title") or ""
        
        if not query:
            return ToolOutput(
                success=False,
                data={"intent": intent},
                error="No query or entity provided"
            )
        
        dry_run = self.get_input(inputs, "dry_run", False)
        approve_payment = bool(self.get_input(inputs, "approve_payment", False))
        params = self.get_input(inputs, "params", {}) or {}
        
        # Setup
        log_dir = Path.home() / ".sparkai_data" / "browser_logs"
        replay_log = ReplayLog(log_dir)
        run_id = f"{intent}_{hash(query) % 10000}"
        replay_log.start_run(run_id)
        
        # We use the process-wide BrowserSession so the CDP connection lives
        # between calls — "next song" doesn't pay the reconnect cost, and a
        # follow-up control intent ("pause") can act on the same live tab.
        # Dry-run callers get a private runtime because dry_run is a flag on
        # the runtime instance and the shared session is always real.
        session = None if dry_run else get_browser_session()
        private_runtime: PlaywrightRuntime | None = None

        try:
            if session is not None:
                runtime = await session.runtime()
            else:
                private_runtime = PlaywrightRuntime(dry_run=True)
                await private_runtime.connect()
                runtime = private_runtime

            # Reuse the adapter's tab if it's already open (so "play another
            # song" updates the existing YouTube tab instead of stacking a
            # new one), then bring Chrome to the foreground.
            host_hint = None
            base_url = getattr(adapter_class, "base_url", None) or ""
            if base_url:
                from urllib.parse import urlparse
                host = urlparse(base_url).netloc.lower()
                host_hint = host.removeprefix("www.") if host else None

            page = await runtime.find_or_create_page(host_hint)
            await runtime.bring_to_front(page)

            # Create adapter and flow
            adapter = adapter_class()
            adapter.verifier = GoalVerifier()
            
            flow = Flow(
                adapter=adapter,
                intent=query,
                run_id=run_id,
                page=page,
                runtime=runtime,
                approve_payment=approve_payment,
                initial_context={
                    "params": params,
                    "entity": self.get_input(inputs, "entity", None) or {},
                },
            )
            
            # Run flow
            result = await flow.run()
            
            return ToolOutput(
                success=result.success,
                data={
                    "intent": intent,
                    "state": result.state.value,
                    "automated": True,
                    "message": f"Flow completed in state {result.state.value}",
                    "context": result.data,
                    "dry_run": dry_run,
                    "approve_payment": approve_payment,
                },
                error=(result.error.detail if (not result.success and result.error) else None),
            )
            
        except Exception as e:
            logger.exception("BrowserAgentTool failed")
            return ToolOutput(
                success=False,
                data={"intent": intent},
                error=str(e)
            )
        finally:
            replay_log.end_run()
            # Only disconnect the private (dry-run) runtime — the shared
            # session must stay alive across calls.
            if private_runtime is not None:
                try:
                    await private_runtime.disconnect()
                except Exception:
                    logger.debug("private runtime disconnect failed", exc_info=True)


# Register adapters
from .adapters.youtube import YouTubeAdapter
from .adapters.amazon import AmazonAdapter
from .adapters.spotify import SpotifyAdapter
from .adapters.daraz import DarazAdapter
from .adapters.booking import BookingAdapter

register_adapter("youtube_play", YouTubeAdapter)
register_adapter("spotify_play", SpotifyAdapter)
# Commerce: Daraz is the primary "buy_product" target on this user's
# region (Nepal). Amazon stays registered under a distinct intent so
# the LLM can route to it when the entity is clearly an Amazon listing.
register_adapter("daraz_buy", DarazAdapter)
register_adapter("amazon_buy", AmazonAdapter)
register_adapter("buy_product", DarazAdapter)  # default for now
register_adapter("book_hotel", BookingAdapter)
register_adapter("booking_hotel", BookingAdapter)


__all__ = ["BrowserAgentTool", "register_adapter"]
