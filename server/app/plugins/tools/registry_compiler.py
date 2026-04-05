from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from app.path.manager import PathManager


RegistryDocument = Dict[str, Any]
ToolEntry = Dict[str, Any]


def load_registry_document(path: Path | None = None) -> RegistryDocument:
    registry_path = path or PathManager().get_tools_registry_file()
    return json.loads(registry_path.read_text(encoding="utf-8"))


def iter_tool_entries(document: RegistryDocument) -> Iterable[Tuple[str, ToolEntry]]:
    for category_name, category_data in document.get("categories", {}).items():
        for tool in category_data.get("tools", []):
            if isinstance(tool, dict):
                yield category_name, tool


def count_registry_tools(document: RegistryDocument) -> int:
    return sum(1 for _category, _tool in iter_tool_entries(document))


def build_tool_index_document(
    document: RegistryDocument,
    *,
    exclude_tools: set[str] | None = None,
) -> Dict[str, Any]:
    excluded = (
        _normalize_tool_name_set(exclude_tools)
        if exclude_tools is not None
        else get_default_generated_file_excludes()["tool_index"]
    )
    tools: List[Dict[str, Any]] = []
    for _category_name, tool in iter_tool_entries(document):
        if str(tool.get("tool_name", "")).strip() in excluded:
            continue
        examples = tool.get("examples") or []
        # tool_index.json is intentionally slim because PQH reads it frequently
        # and we do not want to ship the full registry payload into the LLM path.
        tools.append(
            {
                "name": tool["tool_name"],
                "description": tool["description"],
                "example_triggers": _derive_example_triggers(examples, tool["tool_name"]),
            }
        )

    return {
        "version": str(document.get("version", "unknown")),
        "source": "tool_registry.json",
        "total_tools": len(tools),
        "tools": tools,
    }
def build_manifest_document(
    document: RegistryDocument,
    *,
    exclude_tools: set[str] | None = None,
) -> Dict[str, Any]:
    excluded = (
        _normalize_tool_name_set(exclude_tools)
        if exclude_tools is not None
        else get_default_generated_file_excludes()["manifest"]
    )
    plugins: List[Dict[str, Any]] = []
    for _category_name, tool in iter_tool_entries(document):
        if str(tool.get("tool_name", "")).strip() in excluded:
            continue
        plugins.append(
            {
                "tool_name": tool["tool_name"],
                "module": tool["module"],
                "class_name": tool["class_name"],
            }
        )

    return {
        "version": str(document.get("version", "unknown")),
        "source": "server/tools",
        "registry_relpath": "registry/tool_registry.json",
        "plugins": plugins,
        "total_tools": len(plugins),
    }


def validate_registry_document(
    document: RegistryDocument,
    *,
    tools_root: Path | None = None,
) -> List[str]:
    errors: List[str] = []
    categories = document.get("categories")
    if not isinstance(categories, dict) or not categories:
        return ["tool registry must define non-empty categories"]

    actual_total = count_registry_tools(document)
    declared_total = document.get("total_tools")
    if declared_total is not None and int(declared_total) != actual_total:
        errors.append(
            f"tool_registry total_tools mismatch: declared={declared_total} actual={actual_total}"
        )

    seen_names: set[str] = set()
    tools_dir = (tools_root or PathManager().get_tools_dir()) / "tools"
    ast_cache: Dict[Path, ast.AST] = {}

    for category_name, tool in iter_tool_entries(document):
        tool_name = str(tool.get("tool_name", "")).strip()
        if not tool_name:
            errors.append(f"{category_name}: tool missing tool_name")
            continue
        if tool_name in seen_names:
            errors.append(f"duplicate tool_name detected: {tool_name}")
            continue
        seen_names.add(tool_name)

        for required_field in ("description", "execution_target", "params_schema", "output_schema", "module", "class_name", "examples"):
            if required_field not in tool:
                errors.append(f"{tool_name}: missing required field '{required_field}'")

        if tool.get("execution_target") not in {"server", "client"}:
            errors.append(f"{tool_name}: execution_target must be 'server' or 'client'")
        if not isinstance(tool.get("params_schema"), dict):
            errors.append(f"{tool_name}: params_schema must be an object")
        if not isinstance(tool.get("output_schema"), dict):
            errors.append(f"{tool_name}: output_schema must be an object")
        if not isinstance(tool.get("metadata"), dict):
            errors.append(f"{tool_name}: metadata must be an object")
        if not isinstance(tool.get("examples"), list):
            errors.append(f"{tool_name}: examples must be an array")
        if "semantic_tags" in tool and not isinstance(tool.get("semantic_tags"), list):
            errors.append(f"{tool_name}: semantic_tags must be an array when provided")

        module = str(tool.get("module", "")).strip()
        class_name = str(tool.get("class_name", "")).strip()
        module_path = _resolve_module_source_path(module, tools_dir)
        if not module_path.exists():
            errors.append(f"{tool_name}: module path not found for '{module}'")
            continue

        tree = ast_cache.get(module_path)
        if tree is None:
            tree = ast.parse(module_path.read_text(encoding="utf-8"))
            ast_cache[module_path] = tree

        if not any(isinstance(node, ast.ClassDef) and node.name == class_name for node in ast.walk(tree)):
            errors.append(f"{tool_name}: class '{class_name}' not found in module '{module}'")

    return errors


def sync_generated_tool_files(
    write: bool = False,
    *,
    exclude_from_index: set[str] | None = None,
    exclude_from_manifest: set[str] | None = None,
) -> Dict[str, Any]:
    path_manager = PathManager()
    registry_path = path_manager.get_tools_registry_file()
    index_path = path_manager.get_tools_index_file()
    manifest_path = path_manager.get_tools_manifest_file()

    document = load_registry_document(registry_path)
    errors = validate_registry_document(document, tools_root=path_manager.get_tools_dir())
    if errors:
        raise RuntimeError("Tool registry validation failed:\n- " + "\n- ".join(errors))

    excludes = get_default_generated_file_excludes()
    index_excludes = (
        _normalize_tool_name_set(exclude_from_index)
        if exclude_from_index is not None
        else excludes["tool_index"]
    )
    manifest_excludes = (
        _normalize_tool_name_set(exclude_from_manifest)
        if exclude_from_manifest is not None
        else excludes["manifest"]
    )

    expected_index = build_tool_index_document(document, exclude_tools=index_excludes)
    expected_manifest = build_manifest_document(document, exclude_tools=manifest_excludes)

    changed_index = _sync_json_file(index_path, expected_index, write=write)
    changed_manifest = _sync_json_file(manifest_path, expected_manifest, write=write)

    return {
        "registry_path": str(registry_path),
        "index_path": str(index_path),
        "manifest_path": str(manifest_path),
        "changed_index": changed_index,
        "changed_manifest": changed_manifest,
        "tool_count": count_registry_tools(document),
        "index_tool_count": len(expected_index.get("tools", [])),
        "manifest_tool_count": len(expected_manifest.get("plugins", [])),
        "excluded_from_index": sorted(index_excludes),
        "excluded_from_manifest": sorted(manifest_excludes),
    }


def should_autowrite_generated_tool_files() -> bool:
    if getattr(sys, "frozen", False):
        return False
    raw = str(os.environ.get("JARVIS_TOOLS_AUTOGENERATE", "1")).strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _sync_json_file(path: Path, expected: Dict[str, Any], *, write: bool) -> bool:
    serialized = json.dumps(expected, indent=2, ensure_ascii=True) + "\n"
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    if current == serialized:
        return False
    if not write:
        raise RuntimeError(f"Generated file drift detected: {path}")
    path.write_text(serialized, encoding="utf-8")
    return True


def _derive_example_triggers(examples: Any, tool_name: str) -> List[str]:
    triggers: List[str] = []
    if isinstance(examples, list):
        for item in examples:
            if not isinstance(item, dict):
                continue
            utterance = str(item.get("user_utterance", "")).strip()
            if utterance:
                triggers.append(utterance)
    if triggers:
        return triggers[:3]
    return [tool_name.replace("_", " ")]


def get_default_generated_file_excludes() -> Dict[str, set[str]]:
    try:
        from scripts.sync_index_manifest_with_registry import (
            get_default_generated_file_excludes as get_script_defaults,
        )

        defaults = get_script_defaults()
    except Exception:
        defaults = {}

    return {
        "tool_index": _normalize_tool_name_set(defaults.get("tool_index")),
        "manifest": _normalize_tool_name_set(defaults.get("manifest")),
    }


def _normalize_tool_name_set(values: Any) -> set[str]:
    if not values:
        return set()
    return {
        str(value).strip()
        for value in values
        if str(value).strip()
    }


def _resolve_module_source_path(module_name: str, tools_dir: Path) -> Path:
    rel_path = Path(*module_name.split("."))
    direct = tools_dir / rel_path.with_suffix(".py")
    if direct.exists():
        return direct
    return tools_dir / rel_path / "__init__.py"
