"""Base adapter interface."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class SiteCapabilities:
    supports_checkout: bool = False
    requires_login: bool = False
    high_bot_detection: bool = False
    supports_autofill: bool = True
    supports_dry_run: bool = True


class SiteAdapter(ABC):
    """Base class for site-specific adapters."""
    
    name: str
    base_url: str
    capabilities: SiteCapabilities
    
    def __init__(self):
        self.verifier = None  # Set by flow
    
    @abstractmethod
    async def do_init(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        """Initialize flow."""
        pass
    
    @abstractmethod
    async def do_search(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        """Perform search."""
        pass
    
    @abstractmethod
    async def do_select(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        """Select result."""
        pass
    
    async def do_form_fill(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        """Fill form (optional)."""
        return None
    
    async def do_review(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        """Review before action (optional)."""
        return None
    
    async def do_user_confirm(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        """User confirmation (optional)."""
        return None
    
    @abstractmethod
    async def verify_goal_completed(self, page: Any, intent: str, ctx: dict, runtime: Any) -> bool:
        """Verify goal was achieved."""
        pass
