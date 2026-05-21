"""Tool registry — now populated exclusively by PluginManager auto-discovery.

The JSON-based loading path has been removed. ToolMetadata and ToolRegistry
remain as the canonical in-memory data structures that PluginManager writes to.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ToolMetadata:
    tool_name: str
    description: str
    execution_target: str
    module: str
    class_name: str
    params_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    metadata: Dict[str, Any]
    examples: List[Dict[str, Any]]
    semantic_tags: List[str]
    category: str


class ToolRegistry:
    _instance: "ToolRegistry | None" = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.tools: Dict[str, ToolMetadata] = {}
            self.categories: Dict[str, List[str]] = {}
            self.server_tools: List[str] = []
            self.client_tools: List[str] = []
            self.registry_path: Optional[str] = None
            self.version: str = "plugin-only"
            self._initialized = True

    def clear(self) -> None:
        self.tools.clear()
        self.categories.clear()
        self.server_tools.clear()
        self.client_tools.clear()

    def get_tool(self, tool_name: str) -> Optional[ToolMetadata]:
        return self.tools.get(tool_name)

    def validate_tool(self, tool_name: str) -> bool:
        return tool_name in self.tools

    def get_tools_by_target(self, target: str) -> List[str]:
        if target == "server":
            return self.server_tools.copy()
        if target == "client":
            return self.client_tools.copy()
        return []

    def get_tools_by_category(self, category: str) -> List[str]:
        return self.categories.get(category, []).copy()

    def get_all_tools(self) -> Dict[str, ToolMetadata]:
        return self.tools.copy()


tool_registry = ToolRegistry()


def get_tool_registry() -> ToolRegistry:
    """Return the singleton registry. Populated by PluginManager at startup."""
    return tool_registry


def load_tool_registry(path: Optional[str] = None, force_reload: bool = False) -> None:
    """No-op kept for backward compatibility. Plugins are the source of truth."""
    pass
