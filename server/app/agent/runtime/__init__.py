from importlib import import_module

__all__ = [
    "SmartContextService",
    "get_smart_context_service",
    "CodeContextService",
    "get_code_context_service",
    "CapabilityService",
    "get_capability_service",
    "is_meta_query",
    "try_handle_meta_query",
]


_EXPORT_MODULES = {
    "SmartContextService": "app.agent.runtime.smart_context_service",
    "get_smart_context_service": "app.agent.runtime.smart_context_service",
    "CodeContextService": "app.agent.runtime.code_context_service",
    "get_code_context_service": "app.agent.runtime.code_context_service",
    "CapabilityService": "app.agent.runtime.capability_service",
    "get_capability_service": "app.agent.runtime.capability_service",
    "is_meta_query": "app.agent.runtime.meta_query_router",
    "try_handle_meta_query": "app.agent.runtime.meta_query_router",
}


def __getattr__(name: str):
    module_name = _EXPORT_MODULES.get(name)
    if not module_name:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value

