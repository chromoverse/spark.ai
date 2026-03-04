from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from tools_plugin.registry.loader import get_tool_registry


@dataclass(frozen=True)
class PluginSpec:
    tool_name: str
    module: str
    class_name: str


class ToolInstanceRegistry:
    def __init__(self):
        self.instances: Dict[str, Any] = {}

    def register(self, name: str, instance: Any) -> None:
        self.instances[name] = instance

    def get(self, name: str) -> Any | None:
        return self.instances.get(name)

    def count(self) -> int:
        return len(self.instances)


_instance_registry = ToolInstanceRegistry()


def load_all_tools() -> ToolInstanceRegistry:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    registry = get_tool_registry()

    for plugin in manifest.get("plugins", []):
        if not plugin.get("tool_name") or not plugin.get("module") or not plugin.get("class_name"):
            continue
        spec = PluginSpec(
            tool_name=str(plugin["tool_name"]),
            module=str(plugin["module"]),
            class_name=str(plugin["class_name"]),
        )
        if _instance_registry.get(spec.tool_name):
            continue
        # Keep module loading manifest-driven so new entries auto-load on next run.
        module_name = spec.module
        if not module_name.startswith("tools_plugin.tools."):
            module_name = f"tools_plugin.tools.{module_name}"
        module = importlib.import_module(module_name)
        cls = getattr(module, spec.class_name)
        instance = cls()
        if not registry.validate_tool(spec.tool_name):
            continue
        if hasattr(instance, "set_schemas"):
            metadata = registry.get_tool(spec.tool_name)
            if metadata:
                instance.set_schemas(metadata.params_schema, metadata.output_schema)
        _instance_registry.register(spec.tool_name, instance)

    return _instance_registry


def get_tool_for_execution(tool_name: str) -> Any | None:
    instance = _instance_registry.get(tool_name)
    if instance:
        return instance
    load_all_tools()
    return _instance_registry.get(tool_name)
