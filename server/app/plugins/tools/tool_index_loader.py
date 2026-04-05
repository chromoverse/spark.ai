from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

from app.path.manager import PathManager
from .registry_compiler import (
    build_tool_index_document,
    load_registry_document,
    should_autowrite_generated_tool_files,
    sync_generated_tool_files,
)


def _build_index_from_registry() -> List[Dict[str, Any]]:
    document = load_registry_document()
    return build_tool_index_document(document).get("tools", [])


@lru_cache(maxsize=1)
def get_tools_index(index_path: str = "") -> List[Dict[str, Any]]:
    sync_generated_tool_files(write=should_autowrite_generated_tool_files())
    path = Path(index_path) if index_path else PathManager().get_tools_index_file()
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle).get("tools", [])
    return _build_index_from_registry()


def clear_tools_index_cache() -> None:
    get_tools_index.cache_clear()

