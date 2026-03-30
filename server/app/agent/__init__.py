# app/agent/__init__.py
"""
Agent module — hosts agent-facing layers (chat runtime + client adapters).
Runtime tools and registry are loaded directly from `server/tools`.
"""

from app.agent.runtime import (
    CapabilityService,
    CodeContextService,
    SmartContextService,
    get_capability_service,
    get_code_context_service,
    get_smart_context_service,
    is_meta_query,
    try_handle_meta_query,
)

__all__ = [
    "CapabilityService",
    "CodeContextService",
    "SmartContextService",
    "get_capability_service",
    "get_code_context_service",
    "get_smart_context_service",
    "is_meta_query",
    "try_handle_meta_query",
]
