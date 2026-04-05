# app/agent/__init__.py
"""
Agent module — hosts agent-facing layers (chat runtime + client adapters).
Runtime tools and registry are loaded directly from `server/tools`.
"""

from importlib import import_module

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


_RUNTIME_EXPORTS = {
    "CapabilityService",
    "CodeContextService",
    "SmartContextService",
    "get_capability_service",
    "get_code_context_service",
    "get_smart_context_service",
    "is_meta_query",
    "try_handle_meta_query",
}


def __getattr__(name: str):
    if name in _RUNTIME_EXPORTS:
        module = import_module("app.agent.runtime")
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
