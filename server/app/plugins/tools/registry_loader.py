from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.path.manager import PathManager
from app.plugins.tools.registry_compiler import (
    load_registry_document,
    should_autowrite_generated_tool_files,
    sync_generated_tool_files,
)

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
            self.version: str = "unknown"
            self._initialized = True

    def clear(self) -> None:
        self.tools.clear()
        self.categories.clear()
        self.server_tools.clear()
        self.client_tools.clear()
        self.registry_path = None
        self.version = "unknown"

    def load(self, registry_path: Optional[str] = None, force_reload: bool = False) -> None:
        if self.tools and not force_reload:
            logger.warning("Tool registry already loaded. Use force_reload=True to reload.")
            return

        if force_reload:
            self.clear()

        sync_generated_tool_files(write=should_autowrite_generated_tool_files())
        try:
            from app.plugins.tools.tool_index_loader import clear_tools_index_cache

            clear_tools_index_cache()
        except Exception:
            pass
        path = self._resolve_registry_path(registry_path)
        data = load_registry_document(path)

        self.registry_path = str(path.resolve())
        self.version = str(data.get("version", "unknown"))

        categories = data.get("categories", {})
        for category_name, category_data in categories.items():
            loaded_names: List[str] = []

            for tool_def in category_data.get("tools", []):
                tool_name = tool_def["tool_name"]
                tool = ToolMetadata(
                    tool_name=tool_name,
                    description=tool_def["description"],
                    execution_target=tool_def["execution_target"],
                    module=tool_def["module"],
                    class_name=tool_def["class_name"],
                    params_schema=tool_def["params_schema"],
                    output_schema=tool_def["output_schema"],
                    metadata=tool_def.get("metadata", {}),
                    examples=tool_def.get("examples", []),
                    semantic_tags=[str(item).strip() for item in tool_def.get("semantic_tags", []) if str(item).strip()],
                    category=category_name,
                )
                self.tools[tool_name] = tool
                loaded_names.append(tool_name)

                if tool.execution_target == "server":
                    self.server_tools.append(tool_name)
                elif tool.execution_target == "client":
                    self.client_tools.append(tool_name)

            self.categories[category_name] = loaded_names

        logger.info(
            "Loaded runtime tool registry v%s (%s tools) from %s",
            self.version,
            len(self.tools),
            path,
        )

    @staticmethod
    def _resolve_registry_path(registry_path: Optional[str]):
        if registry_path:
            from pathlib import Path

            return Path(registry_path)
        return PathManager().get_tools_registry_file()

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
    if not tool_registry.tools:
        tool_registry.load()
    return tool_registry


def load_tool_registry(path: Optional[str] = None, force_reload: bool = False) -> None:
    tool_registry.load(path, force_reload=force_reload)
