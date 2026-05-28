"""BrowserAgentTool - LLM interface for browser automation."""
import logging
from typing import Any, Dict
from pathlib import Path
from app.plugins.tools.tool_base import BaseTool, ToolOutput
from .runtime.playwright import PlaywrightRuntime
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
        
        # Setup
        log_dir = Path.home() / ".sparkai_data" / "browser_logs"
        replay_log = ReplayLog(log_dir)
        run_id = f"{intent}_{hash(query) % 10000}"
        replay_log.start_run(run_id)
        
        runtime = None
        try:
            # Connect to browser
            runtime = PlaywrightRuntime(dry_run=dry_run)
            await runtime.connect()
            
            # Get or create page
            pages = await runtime.pages()
            if pages:
                page = pages[0]
            else:
                page = await runtime.new_page()
            
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
            if runtime:
                await runtime.disconnect()


# Register adapters
from .adapters.youtube import YouTubeAdapter
from .adapters.amazon import AmazonAdapter

register_adapter("youtube_play", YouTubeAdapter)
register_adapter("buy_product", AmazonAdapter)


__all__ = ["BrowserAgentTool", "register_adapter"]
