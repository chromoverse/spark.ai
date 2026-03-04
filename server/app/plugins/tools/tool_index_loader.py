from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

from .registry_loader import get_tool_registry
from app.utils.path_manager import PathManager


def _build_index_from_registry() -> List[Dict[str, Any]]:
    registry = get_tool_registry()
    tools: List[Dict[str, Any]] = []
    for category, names in registry.categories.items():
        for tool_name in names:
            metadata = registry.get_tool(tool_name)
            if not metadata:
                continue
            tools.append(
                {
                    "name": metadata.tool_name,
                    "description": metadata.description,
                    "category": category,
                    "execution_target": metadata.execution_target,
                }
            )
    return tools


@lru_cache(maxsize=1)
def get_tools_index(index_path: str = "") -> List[Dict[str, Any]]:
    path = Path(index_path) if index_path else PathManager().get_tools_plugin_index_file()
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle).get("tools", [])
    return _build_index_from_registry()

