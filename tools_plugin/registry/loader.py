from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ToolMetadata:
    tool_name: str
    description: str
    execution_target: str
    params_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    metadata: Dict[str, Any]
    category: str


class ToolRegistry:
    def __init__(self):
        self.tools: Dict[str, ToolMetadata] = {}
        self.categories: Dict[str, List[str]] = {}
        self.server_tools: List[str] = []
        self.client_tools: List[str] = []
        self.registry_path: Optional[str] = None

    def load(self, registry_path: Optional[str] = None, force_reload: bool = False) -> None:
        if self.tools and not force_reload:
            return
        if force_reload:
            self.tools.clear()
            self.categories.clear()
            self.server_tools.clear()
            self.client_tools.clear()

        path = Path(registry_path) if registry_path else Path(__file__).resolve().parent / "tool_registry.json"
        if not path.exists():
            raise FileNotFoundError(f"Tool registry not found: {path}")

        data = json.loads(path.read_text(encoding="utf-8"))
        self.registry_path = str(path)
        for category_name, category_data in data.get("categories", {}).items():
            items: List[str] = []
            for tool_def in category_data.get("tools", []):
                tool_name = tool_def["tool_name"]
                tool = ToolMetadata(
                    tool_name=tool_name,
                    description=tool_def["description"],
                    execution_target=tool_def["execution_target"],
                    params_schema=tool_def["params_schema"],
                    output_schema=tool_def["output_schema"],
                    metadata=tool_def.get("metadata", {}),
                    category=category_name,
                )
                self.tools[tool_name] = tool
                items.append(tool_name)
                if tool.execution_target == "server":
                    self.server_tools.append(tool_name)
                elif tool.execution_target == "client":
                    self.client_tools.append(tool_name)
            self.categories[category_name] = items

    def get_tool(self, tool_name: str) -> Optional[ToolMetadata]:
        return self.tools.get(tool_name)

    def get_all_tools(self) -> Dict[str, ToolMetadata]:
        return self.tools.copy()

    def validate_tool(self, tool_name: str) -> bool:
        return tool_name in self.tools


_tool_registry = ToolRegistry()


def get_tool_registry() -> ToolRegistry:
    if not _tool_registry.tools:
        _tool_registry.load()
    return _tool_registry


def load_tool_registry(path: Optional[str] = None, force_reload: bool = False) -> None:
    _tool_registry.load(path, force_reload=force_reload)
