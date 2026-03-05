from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
from pathlib import Path
from typing import Any


def _ensure_repo_root_on_path() -> None:
    # tools_plugin/ -> repo root
    repo_root = Path(__file__).resolve().parent.parent
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)


def _manifest_path() -> Path:
    return Path(__file__).resolve().parent / "manifest.json"


def _load_manifest() -> dict[str, Any]:
    with _manifest_path().open("r", encoding="utf-8") as f:
        return json.load(f)


def _list_tools() -> list[str]:
    manifest = _load_manifest()
    return [
        str(plugin.get("tool_name"))
        for plugin in manifest.get("plugins", [])
        if plugin.get("tool_name")
    ]


def _load_tool_class_from_name(tool_name: str):
    _ensure_repo_root_on_path()
    manifest = _load_manifest()

    for plugin in manifest.get("plugins", []):
        if plugin.get("tool_name") != tool_name:
            continue
        module_rel = str(plugin["module"])
        class_name = str(plugin["class_name"])
        module = importlib.import_module(f"tools_plugin.tools.{module_rel}")
        cls = getattr(module, class_name, None)
        if cls is None:
            raise RuntimeError(f"Class '{class_name}' not found in module '{module_rel}'")
        return cls

    raise RuntimeError(f"Tool '{tool_name}' not found in manifest: {_manifest_path()}")


def _normalize_module_ref(module_ref: str) -> str:
    module_ref = module_ref.strip()
    if module_ref.startswith("tools_plugin."):
        return module_ref
    if module_ref.startswith("tools."):
        return f"tools_plugin.{module_ref}"
    if module_ref.startswith("tools_plugin"):
        return module_ref
    return f"tools_plugin.tools.{module_ref}"


def _load_tool_class_from_import(import_ref: str):
    """
    Supported:
    - tools_plugin.tools.messaging.message_send:MessageSendTool
    - tools.messaging.message_send:MessageSendTool
    - messaging.message_send:MessageSendTool
    - tools_plugin.tools.messaging.message_send   (auto-pick first *Tool class)
    """
    _ensure_repo_root_on_path()

    module_ref = import_ref
    class_name = ""
    if ":" in import_ref:
        module_ref, class_name = import_ref.split(":", 1)

    module = importlib.import_module(_normalize_module_ref(module_ref))
    if class_name:
        cls = getattr(module, class_name, None)
        if cls is None:
            raise RuntimeError(f"Class '{class_name}' not found in module '{module.__name__}'")
        return cls

    for attr_name in dir(module):
        if not attr_name.endswith("Tool"):
            continue
        candidate = getattr(module, attr_name)
        if isinstance(candidate, type):
            return candidate
    raise RuntimeError(f"No '*Tool' class found in module '{module.__name__}'")


def _parse_inputs(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in --inputs: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("--inputs must be a JSON object")
    return data


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Easy tools_plugin runner for any tool in manifest or direct import path."
    )
    parser.add_argument(
        "tool_positional",
        nargs="?",
        default="",
        help="Optional positional tool name (shortcut for --tool).",
    )
    parser.add_argument(
        "inputs_positional",
        nargs="?",
        default="",
        help="Optional positional JSON inputs (shortcut for --inputs).",
    )
    parser.add_argument(
        "--tool",
        default="",
        help="Tool name from manifest.json (default: message_send)",
    )
    parser.add_argument(
        "--import",
        dest="import_ref",
        default="",
        help="Direct module or module:Class ref",
    )
    parser.add_argument(
        "--inputs",
        default='{"contact":"Rajesh Vaiya","message":"Hello, world! Testing message"}',
        help="JSON object passed to tool.execute(...)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all available tool names and exit",
    )
    args = parser.parse_args()

    if args.list:
        tools = _list_tools()
        print({"count": len(tools), "tools": tools})
        return

    tool_name = (args.tool or args.tool_positional or "message_send").strip()
    raw_inputs = (args.inputs_positional or args.inputs or "").strip()

    tool_cls = (
        _load_tool_class_from_import(args.import_ref)
        if args.import_ref
        else _load_tool_class_from_name(tool_name)
    )
    inputs = _parse_inputs(raw_inputs)
    tool = tool_cls()
    result = await tool.execute(inputs)
    print({"success": result.success, "error": result.error, "data": result.data})


if __name__ == "__main__":
    asyncio.run(main())
