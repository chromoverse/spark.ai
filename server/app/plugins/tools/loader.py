from __future__ import annotations

import importlib
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.utils.path_manager import PathManager

from .registry_loader import get_tool_registry
from .tool_base import get_tool_instance_registry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PluginSpec:
    tool_name: str
    module: str
    class_name: str


class RuntimeToolsLoader:
    """
    Load tool implementations directly from the bundled/local `server/tools` package.

    Contract:
    1. Load plugin specs from the in-package manifest.
    2. Import plugin modules dynamically from the `tools.*` namespace.
    3. Validate tool names against the tool registry.
    4. Register instantiated tools in the global instance registry.
    """

    def __init__(self):
        self.path_manager = PathManager()
        self.registry = get_tool_registry()

    def load_runtime_tools(self, runtime_tools_path: Path | None = None):
        instance_registry = get_tool_instance_registry()
        root = Path(runtime_tools_path) if runtime_tools_path else self.path_manager.get_tools_dir()
        manifest_path = root / "manifest.json"
        tools_path = root / "tools"

        if not manifest_path.exists():
            raise FileNotFoundError(f"Runtime manifest not found: {manifest_path}")
        if not tools_path.exists():
            raise FileNotFoundError(f"Runtime tools dir not found: {tools_path}")

        specs = self._read_manifest(manifest_path)
        self._ensure_runtime_namespace(root)

        logger.info("=" * 70)
        logger.info("Loading Runtime Tools from %s", tools_path)
        logger.info("=" * 70)

        loaded_count = 0
        for spec in specs:
            if instance_registry.has(spec.tool_name):
                continue
            try:
                tool = self._load_one(spec)
                if not tool:
                    continue

                metadata = self.registry.get_tool(spec.tool_name)
                if metadata:
                    tool.set_schemas(
                        params_schema=metadata.params_schema,
                        output_schema=metadata.output_schema,
                    )
                else:
                    logger.warning("No schema metadata found for tool: %s", spec.tool_name)

                instance_registry.register(tool)
                loaded_count += 1
                logger.info("  [OK] %s <- %s.%s", spec.tool_name, spec.module, spec.class_name)
            except Exception as exc:
                logger.error(
                    "  [FAIL] tool=%s module=%s class=%s error=%s",
                    spec.tool_name,
                    spec.module,
                    spec.class_name,
                    exc,
                )

        logger.info("=" * 70)
        logger.info(
            "Loaded %s new runtime tool instance(s); total=%s",
            loaded_count,
            instance_registry.count(),
        )
        logger.info("=" * 70)

        return instance_registry

    def _load_one(self, spec: PluginSpec) -> Any | None:
        if spec.module.startswith(("tools.tools.", "tools.automation.", "tools.utils.")):
            module_name = spec.module
        elif spec.module.startswith("tools."):
            module_name = f"tools.tools.{spec.module[len('tools.'):]}"
        else:
            module_name = f"tools.tools.{spec.module}"
        module = importlib.import_module(module_name)
        cls = getattr(module, spec.class_name, None)
        if cls is None:
            raise AttributeError(f"Class '{spec.class_name}' not found in module '{spec.module}'")

        tool = cls()
        self._validate_tool_contract(tool, spec.class_name)

        runtime_tool_name = tool.get_tool_name()
        if runtime_tool_name != spec.tool_name:
            raise ValueError(
                f"Manifest tool_name '{spec.tool_name}' mismatch with implementation '{runtime_tool_name}'"
            )

        if not self.registry.validate_tool(runtime_tool_name):
            logger.warning(
                "Tool '%s' present in manifest but absent in registry; skipping",
                runtime_tool_name,
            )
            return None

        return tool

    @staticmethod
    def _validate_tool_contract(tool: Any, class_name: str) -> None:
        required_methods = ("get_tool_name", "set_schemas", "execute")
        missing = [name for name in required_methods if not hasattr(tool, name)]
        if missing:
            raise TypeError(
                f"Loaded tool class '{class_name}' is missing required methods: {', '.join(missing)}"
            )

    @staticmethod
    def _ensure_runtime_namespace(runtime_root: Path) -> None:
        server_root = str(runtime_root.parent)
        if server_root not in sys.path:
            sys.path.insert(0, server_root)

    @staticmethod
    def _read_manifest(manifest_path: Path) -> list[PluginSpec]:
        with manifest_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        specs: list[PluginSpec] = []
        for item in data.get("plugins", []):
            tool_name = item.get("tool_name")
            module = item.get("module")
            class_name = item.get("class_name")

            if not tool_name or not module or not class_name:
                continue

            specs.append(
                PluginSpec(
                    tool_name=str(tool_name),
                    module=str(module),
                    class_name=str(class_name),
                )
            )
        return specs


_runtime_tools_loader: RuntimeToolsLoader | None = None


def get_runtime_tools_loader() -> RuntimeToolsLoader:
    global _runtime_tools_loader
    if _runtime_tools_loader is None:
        _runtime_tools_loader = RuntimeToolsLoader()
    return _runtime_tools_loader

