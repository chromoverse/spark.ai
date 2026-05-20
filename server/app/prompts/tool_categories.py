"""
Tool Category System — Auto-generated from tool_registry.json at startup.

Reads the `category` field from each tool in the registry and builds:
- CATEGORIES: {category_name: description}
- TOOL_TO_CATEGORY: {tool_name: category}
- CATEGORY_TO_TOOLS: {category: [tool_names]}

No hardcoding. Add a new tool with a category field → it appears here automatically.
"""

from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

# Category descriptions (static — these describe intent for PQH)
_CATEGORY_DESCRIPTIONS: Dict[str, str] = {
    "system_control": "Open/close/restart apps, brightness, volume, mic, lock screen, system info, battery, network",
    "file_management": "Find, open, create, delete, move, copy, read files. Organize folders. List directory contents. Run shell commands.",
    "communication": "Send messages, make calls (audio/video), email (read/send/search/organize)",
    "media": "Play/stop/pause music, take screenshots",
    "web_knowledge": "Web research, weather, current location, live info lookup",
    "ai_content": "Generate long text content (articles, notes, plans), summarize documents or conversations",
    "spark_internal": "Open/close Spark window, navigate Spark tabs, open Spark storage, check agent status, inspect tools, manage artifacts",
    "automation": "Multi-step shell tasks with LLM guidance, set reminders, schedule recurring tasks",
    "clipboard_notify": "Read/write clipboard, push OS notifications",
}

# Auto-built at import time from registry
TOOL_TO_CATEGORY: Dict[str, str] = {}
CATEGORY_TO_TOOLS: Dict[str, List[str]] = {}
CATEGORIES: Dict[str, str] = {}


def _build_from_registry() -> None:
    """Scan tool_registry.json and build category mappings."""
    global TOOL_TO_CATEGORY, CATEGORY_TO_TOOLS, CATEGORIES

    try:
        from app.plugins.tools.registry_loader import get_tool_registry
        registry = get_tool_registry()
        if not registry or not registry.tools:
            _build_from_json_file()
            return

        for tool_name, tool in registry.tools.items():
            cat = tool.category or "system_control"
            TOOL_TO_CATEGORY[tool_name] = cat
            CATEGORY_TO_TOOLS.setdefault(cat, []).append(tool_name)
    except Exception:
        _build_from_json_file()

    # Build CATEGORIES from descriptions + any new categories found in tools
    CATEGORIES.update(_CATEGORY_DESCRIPTIONS)
    for cat in CATEGORY_TO_TOOLS:
        if cat not in CATEGORIES:
            CATEGORIES[cat] = f"Tools: {', '.join(CATEGORY_TO_TOOLS[cat][:5])}"

    logger.info(f"📂 Auto-built {len(CATEGORIES)} categories from {len(TOOL_TO_CATEGORY)} tools")


def _build_from_json_file() -> None:
    """Fallback: read directly from tool_registry.json."""
    global TOOL_TO_CATEGORY, CATEGORY_TO_TOOLS

    import json
    from pathlib import Path

    registry_path = Path(__file__).resolve().parents[2] / "tools" / "registry" / "tool_registry.json"
    if not registry_path.exists():
        logger.warning("tool_registry.json not found, using empty categories")
        return

    data = json.loads(registry_path.read_text(encoding="utf-8"))
    for cat_data in data.get("categories", {}).values():
        for tool in cat_data.get("tools", []):
            name = tool.get("tool_name", "")
            cat = tool.get("category", "system_control")
            if name:
                TOOL_TO_CATEGORY[name] = cat
                CATEGORY_TO_TOOLS.setdefault(cat, []).append(name)


def get_category_for_tool(tool_name: str) -> Optional[str]:
    return TOOL_TO_CATEGORY.get(tool_name)


def get_tools_in_category(category: str) -> List[str]:
    return CATEGORY_TO_TOOLS.get(category, [])


def get_all_categories() -> Dict[str, str]:
    return CATEGORIES


# Auto-build on import
_build_from_registry()
