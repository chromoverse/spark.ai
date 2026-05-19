"""
PluginManager — discovers plugin manifests under `plugins/installed/`,
validates that declared tools exist in the active ToolRegistry, registers
declared skills with the SkillEngine, and tracks per-plugin runtime state.

Tools shipped by a plugin can live in **two** places:

  1. Legacy: `server/tools/tools/<category>/...` — listed in the central
     `tool_registry.json`. The plugin manifest's `tools` array claims
     ownership for documentation purposes.

  2. Plugin-local: `installed/<plugin>/tools/*.py` — auto-discovered by
     this manager. Each tool class declares its own metadata via class
     attributes (TOOL_DESCRIPTION, EXECUTION_TARGET, PARAMS_SCHEMA,
     OUTPUT_SCHEMA, ...) so no JSON edits are needed.

Both layouts coexist freely; the registry is union of the two.
"""
from __future__ import annotations

import importlib.util
import inspect
import logging
import sys
from pathlib import Path
from types import ModuleType
from typing import Dict, List, Optional, Tuple

from app.plugins.tools.registry_loader import ToolMetadata, get_tool_registry
from app.plugins.tools.tool_base import get_tool_instance_registry

from plugins.models import PluginManifest, PluginState
from plugins.skills.skill_engine import SkillEngine, get_skill_engine

logger = logging.getLogger(__name__)


# Default location for plugin bundles (server/plugins/installed/)
DEFAULT_PLUGINS_DIR = Path(__file__).resolve().parent / "installed"


class PluginManager:
    """Singleton-style plugin registry + lifecycle controller."""

    def __init__(self, plugins_dir: Optional[Path] = None) -> None:
        self.plugins_dir: Path = plugins_dir or DEFAULT_PLUGINS_DIR
        self.plugins: Dict[str, PluginState] = {}
        self.skill_engine: SkillEngine = get_skill_engine()
        self._loaded: bool = False

    # ── discovery ────────────────────────────────────────────────────────

    async def discover_and_load(self) -> None:
        """Scan `plugins/installed/` for `plugin.json` manifests and load each."""
        if not self.plugins_dir.is_dir():
            logger.warning("Plugin directory does not exist: %s", self.plugins_dir)
            self._loaded = True
            return

        for entry in sorted(self.plugins_dir.iterdir()):
            if not entry.is_dir():
                continue
            manifest_path = entry / "plugin.json"
            if not manifest_path.exists():
                continue

            try:
                manifest = PluginManifest.from_file(manifest_path)
            except Exception as exc:
                logger.error("Failed to read manifest %s: %s", manifest_path, exc)
                self.plugins[entry.name] = PluginState(
                    manifest=PluginManifest(name=entry.name, enabled=False),
                    plugin_dir=entry,
                    status="failed",
                    error=str(exc),
                )
                continue

            if not manifest.enabled:
                logger.info("Plugin %s is disabled — skipping", manifest.name)
                self.plugins[manifest.name] = PluginState(
                    manifest=manifest, plugin_dir=entry, status="disabled",
                )
                continue

            self._load_one(manifest, entry)

        self._loaded = True
        logger.info(
            "PluginManager: %d plugin(s) loaded, %d skill(s) registered",
            sum(1 for p in self.plugins.values() if p.status == "loaded"),
            len(self.skill_engine.skills),
        )

    def _load_one(self, manifest: PluginManifest, plugin_dir: Path) -> None:
        # Dependency check: every name in manifest.dependencies must already
        # be present in self.plugins as 'loaded'.
        missing_deps = self._check_dependencies(manifest)
        if missing_deps:
            logger.warning(
                "Plugin %s skipped — missing dependencies: %s",
                manifest.name, missing_deps,
            )
            self.plugins[manifest.name] = PluginState(
                manifest=manifest, plugin_dir=plugin_dir,
                status="failed",
                error=f"Missing dependencies: {missing_deps}",
            )
            return

        # 1. Auto-discover tools that live INSIDE this plugin's tools/ dir.
        #    These get registered into the live ToolRegistry with metadata
        #    pulled from class attributes — no JSON edit needed.
        shipped_count = self._discover_plugin_tools(manifest, plugin_dir)

        # 2. Validate that any tool the manifest claims (legacy + shipped)
        #    exists in the active registry.
        tool_count, missing_tools = self._register_plugin_tools(manifest)

        # 3. Register skills declared in the manifest.
        skill_count = self._register_plugin_skills(manifest, plugin_dir)

        self.plugins[manifest.name] = PluginState(
            manifest=manifest,
            plugin_dir=plugin_dir,
            status="loaded",
            tool_count=tool_count,
            skill_count=skill_count,
            missing_tools=missing_tools,
        )
        logger.info(
            "Loaded plugin %s v%s — claimed=%d, shipped=%d, skills=%d%s",
            manifest.name, manifest.version,
            tool_count, shipped_count, skill_count,
            f", missing: {missing_tools}" if missing_tools else "",
        )

    # ── helpers ──────────────────────────────────────────────────────────

    def _check_dependencies(self, manifest: PluginManifest) -> List[str]:
        return [
            dep for dep in manifest.dependencies
            if dep not in self.plugins
            or self.plugins[dep].status != "loaded"
        ]

    def _discover_plugin_tools(self, manifest: PluginManifest, plugin_dir: Path) -> int:
        """Auto-discover BaseTool subclasses inside `<plugin_dir>/tools/*.py`.

        Each discovered class becomes a fully-registered tool — its metadata
        is built from class attributes (no JSON registry entry needed) and
        the instance is registered so the executor can find it by name.

        Tool class contract (any attribute may be omitted; sensible defaults
        are used). The class MUST extend `BaseTool`:

            class HelloTool(BaseTool):
                TOOL_DESCRIPTION = "Says hello back to the user."
                EXECUTION_TARGET = "server"     # or "client"
                PARAMS_SCHEMA  = {"who": {"type": "string", "required": True}}
                OUTPUT_SCHEMA  = {"data": {"greeting": {"type": "string"}}}
                EXAMPLES       = [{"user_utterance": "say hi to mom"}]
                SEMANTIC_TAGS  = ["greeting", "demo"]

                def get_tool_name(self): return "hello"
                async def _execute(self, inputs): ...

        Returns the number of tools registered from this plugin's tools/ dir.
        """
        from app.plugins.tools.tool_base import BaseTool  # local — avoids early import

        tools_dir = plugin_dir / "tools"
        if not tools_dir.is_dir():
            return 0

        registered = 0
        for py_file in sorted(tools_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue  # skip __init__.py and private files
            try:
                module = self._import_plugin_module(py_file, manifest.name)
            except Exception as exc:
                logger.error(
                    "Plugin %s: failed to import %s: %s",
                    manifest.name, py_file.name, exc,
                )
                continue

            for cls in self._iter_tool_classes(module, BaseTool):
                try:
                    metadata, instance = self._build_tool_from_class(cls, manifest, py_file)
                except Exception as exc:
                    logger.error(
                        "Plugin %s: tool class %s.%s rejected: %s",
                        manifest.name, py_file.stem, cls.__name__, exc,
                    )
                    continue
                self._register_shipped_tool(metadata, instance)
                registered += 1
                logger.info(
                    "  ↳ shipped tool: %s (from %s/%s)",
                    metadata.tool_name, manifest.name, py_file.name,
                )
        return registered

    @staticmethod
    def _import_plugin_module(py_file: Path, plugin_name: str) -> ModuleType:
        """Import a plugin's tool file under a stable, isolated module name."""
        module_name = f"plugins._installed.{plugin_name}.tools.{py_file.stem}"
        spec = importlib.util.spec_from_file_location(module_name, py_file)
        if not spec or not spec.loader:
            raise ImportError(f"Could not build spec for {py_file}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _iter_tool_classes(module: ModuleType, base_cls: type):
        """Yield BaseTool subclasses defined in (not just imported into) module."""
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if obj is base_cls or not issubclass(obj, base_cls):
                continue
            # Only classes actually defined in this module — skip re-imports.
            if obj.__module__ != module.__name__:
                continue
            if inspect.isabstract(obj):
                continue
            yield obj

    @staticmethod
    def _build_tool_from_class(
        cls: type, manifest: PluginManifest, source: Path,
    ) -> Tuple[ToolMetadata, "BaseTool"]:  # type: ignore[name-defined]
        """Instantiate the tool class and read class-level metadata attributes."""
        instance = cls()  # may raise — caller catches
        tool_name = instance.get_tool_name()
        if not tool_name:
            raise ValueError(f"{cls.__name__}.get_tool_name() returned empty string")

        params_schema = dict(getattr(cls, "PARAMS_SCHEMA", {}) or {})
        output_schema = dict(getattr(cls, "OUTPUT_SCHEMA", {}) or {})
        execution_target = str(getattr(cls, "EXECUTION_TARGET", "server")).strip() or "server"
        if execution_target not in {"server", "client"}:
            raise ValueError(
                f"{cls.__name__}.EXECUTION_TARGET must be 'server' or 'client'"
            )
        examples = list(getattr(cls, "EXAMPLES", []) or [])
        semantic_tags = [str(t).strip() for t in (getattr(cls, "SEMANTIC_TAGS", []) or []) if str(t).strip()]
        description = str(getattr(cls, "TOOL_DESCRIPTION", "") or "").strip()
        if not description:
            description = (cls.__doc__ or "").strip().split("\n", 1)[0]

        # Bind schemas onto the instance for runtime validation.
        instance.set_schemas(params_schema=params_schema, output_schema=output_schema)

        metadata = ToolMetadata(
            tool_name=tool_name,
            description=description,
            execution_target=execution_target,
            module=f"plugins._installed.{manifest.name}.tools.{source.stem}",
            class_name=cls.__name__,
            params_schema=params_schema,
            output_schema=output_schema,
            metadata={
                "source": "plugin",
                "plugin": manifest.name,
                "plugin_version": manifest.version,
                "file": str(source.relative_to(source.parents[2])).replace("\\", "/"),
            },
            examples=examples,
            semantic_tags=semantic_tags,
            category=manifest.name,
        )
        return metadata, instance

    @staticmethod
    def _register_shipped_tool(metadata: ToolMetadata, instance) -> None:
        """Insert the tool into the live ToolRegistry + ToolInstanceRegistry.

        We don't touch `tool_registry.json` — these registrations are purely
        in-memory and rebuilt at every boot from the plugin's source files.
        """
        registry = get_tool_registry()
        if metadata.tool_name in registry.tools:
            logger.warning(
                "Tool %r already registered (existing source=%s); plugin-shipped version will not override.",
                metadata.tool_name,
                registry.tools[metadata.tool_name].metadata.get("source", "registry"),
            )
            return

        # Add to ToolRegistry data structures
        registry.tools[metadata.tool_name] = metadata
        if metadata.execution_target == "server":
            registry.server_tools.append(metadata.tool_name)
        elif metadata.execution_target == "client":
            registry.client_tools.append(metadata.tool_name)
        registry.categories.setdefault(metadata.category, []).append(metadata.tool_name)

        # Add to ToolInstanceRegistry so the executor can find it
        get_tool_instance_registry().register(instance)

    def _register_plugin_tools(self, manifest: PluginManifest) -> tuple[int, List[str]]:
        """Validate that every declared tool exists in the active ToolRegistry.

        Tools themselves are registered by the existing registry loader; the
        plugin manifest just claims ownership for documentation/UX purposes.
        Returns (count_present, list_missing).
        """
        try:
            registry = get_tool_registry()
        except Exception as exc:
            logger.error("Tool registry unavailable while loading %s: %s",
                         manifest.name, exc)
            return 0, list(manifest.tools)

        missing: List[str] = []
        present = 0
        for tool_name in manifest.tools:
            if registry.validate_tool(tool_name):
                present += 1
            else:
                missing.append(tool_name)
        return present, missing

    def _register_plugin_skills(self, manifest: PluginManifest, plugin_dir: Path) -> int:
        """Load skill YAML files declared by the plugin into the SkillEngine."""
        registered = 0
        for entry in manifest.skills:
            file_rel = entry.get("file") if isinstance(entry, dict) else None
            if not file_rel:
                continue
            skill_path = (plugin_dir / file_rel).resolve()
            if not skill_path.exists():
                logger.warning(
                    "Plugin %s declares missing skill file: %s",
                    manifest.name, skill_path,
                )
                continue
            skill = self.skill_engine.register_skill_from_path(
                skill_path, plugin=manifest.name,
            )
            if skill:
                registered += 1
        return registered

    # ── public API ───────────────────────────────────────────────────────

    def get_plugin(self, name: str) -> Optional[PluginState]:
        return self.plugins.get(name)

    def list_plugins(self) -> List[dict]:
        return [p.to_dict() for p in self.plugins.values()]

    async def reload_plugin(self, name: str) -> bool:
        """Hot-reload a single plugin's manifest + skills (development helper)."""
        state = self.plugins.get(name)
        plugin_dir = state.plugin_dir if state else (self.plugins_dir / name)
        manifest_path = plugin_dir / "plugin.json"
        if not manifest_path.exists():
            return False

        # Drop existing skills owned by this plugin
        self.skill_engine.unregister_for_plugin(name)
        self.plugins.pop(name, None)

        try:
            manifest = PluginManifest.from_file(manifest_path)
        except Exception as exc:
            logger.error("reload_plugin(%s) failed parsing manifest: %s", name, exc)
            return False

        if not manifest.enabled:
            self.plugins[manifest.name] = PluginState(
                manifest=manifest, plugin_dir=plugin_dir, status="disabled",
            )
            return True

        self._load_one(manifest, plugin_dir)
        return self.plugins.get(manifest.name, PluginState(
            manifest=manifest, plugin_dir=plugin_dir,
        )).status == "loaded"

    @property
    def is_loaded(self) -> bool:
        return self._loaded


# ── singleton ────────────────────────────────────────────────────────────────

_instance: Optional[PluginManager] = None


def get_plugin_manager() -> PluginManager:
    global _instance
    if _instance is None:
        _instance = PluginManager()
    return _instance


__all__ = ["PluginManager", "get_plugin_manager", "DEFAULT_PLUGINS_DIR"]
