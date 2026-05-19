from __future__ import annotations

import json
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


_cached_index: List[Dict[str, Any]] | None = None


def get_tools_index(index_path: str = "") -> List[Dict[str, Any]]:
    """Return the unified tool index for PQH.

    Combines:
      1. Static tools from tool_index.json (generated from tool_registry.json)
      2. Plugin-shipped tools registered in the live ToolRegistry at boot

    This ensures PQH sees every tool regardless of whether it came from the
    legacy JSON registry or a plugin's tools/ directory.
    """
    global _cached_index
    if _cached_index is not None:
        return _cached_index

    sync_generated_tool_files(write=should_autowrite_generated_tool_files())
    path = Path(index_path) if index_path else PathManager().get_tools_index_file()
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            base = json.load(handle).get("tools", [])
    else:
        base = _build_index_from_registry()

    # Merge plugin-shipped tools that aren't in the static index
    merged = _merge_plugin_tools(base)
    _cached_index = merged
    return merged


def _merge_plugin_tools(base: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Append any tools from the live ToolRegistry that aren't already in the
    static index. These are plugin-shipped tools auto-discovered at boot."""
    try:
        from .registry_loader import get_tool_registry
        registry = get_tool_registry()
    except Exception:
        return base

    existing_names = {t.get("name", "") for t in base}
    extras: List[Dict[str, Any]] = []

    for name, meta in registry.tools.items():
        if name in existing_names:
            continue
        # This tool exists in the live registry but not in the static file
        # → it was registered by a plugin at boot time.
        examples = meta.examples or []
        triggers = []
        for ex in examples[:3]:
            if isinstance(ex, dict):
                u = ex.get("user_utterance", "")
                if u:
                    triggers.append(u)
        if not triggers:
            triggers = [name.replace("_", " ")]

        extras.append({
            "name": name,
            "description": meta.description,
            "example_triggers": triggers,
        })

    if extras:
        return base + extras
    return base


def clear_tools_index_cache() -> None:
    global _cached_index
    _cached_index = None

