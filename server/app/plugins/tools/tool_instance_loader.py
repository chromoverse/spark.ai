from __future__ import annotations

from typing import Any

from .loader import get_runtime_tools_loader
from .tool_base import get_tool_instance, get_tool_instance_registry


def load_all_tools():
    return get_runtime_tools_loader().load_runtime_tools()


def get_tool_for_execution(tool_name: str) -> Any | None:
    instance = get_tool_instance(tool_name)
    if instance is not None:
        return instance

    # Re-check manifest and load any newly added plugins on demand.
    load_all_tools()
    return get_tool_instance(tool_name)

