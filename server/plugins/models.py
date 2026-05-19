"""
Plugin & Skill data models.

Plugins are versioned bundles of capabilities. Each plugin owns one or more
already-registered tools (declared by name) plus optional skill definitions —
multi-tool DAGs encoded as YAML — that short-circuit LLM planning for known
recipes.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Plugin manifest ──────────────────────────────────────────────────────────


@dataclass
class PluginManifest:
    """Strongly-typed view of a `plugin.json` file."""

    name: str
    version: str = "0.0.0"
    display_name: str = ""
    description: str = ""
    author: str = "spark-core"
    capabilities: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)
    skills: List[Dict[str, str]] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    config_schema: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True

    @staticmethod
    def from_file(path: Path) -> "PluginManifest":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in {path}: {exc}") from exc

        name = str(data.get("name", "")).strip()
        if not name:
            raise ValueError(f"plugin.json at {path} is missing required field 'name'")

        return PluginManifest(
            name=name,
            version=str(data.get("version", "0.0.0")),
            display_name=str(data.get("display_name", name.title())),
            description=str(data.get("description", "")),
            author=str(data.get("author", "spark-core")),
            capabilities=[str(x) for x in data.get("capabilities", [])],
            tools=[str(x) for x in data.get("tools", [])],
            skills=[dict(x) for x in data.get("skills", []) if isinstance(x, dict)],
            dependencies=[str(x) for x in data.get("dependencies", [])],
            config_schema=dict(data.get("config_schema", {})),
            enabled=bool(data.get("enabled", True)),
        )


# ── Plugin runtime state ─────────────────────────────────────────────────────


@dataclass
class PluginState:
    """Loaded-plugin runtime state — one per discovered plugin."""

    manifest: PluginManifest
    plugin_dir: Path
    status: str = "loaded"            # "loaded" | "disabled" | "failed"
    tool_count: int = 0
    skill_count: int = 0
    missing_tools: List[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.manifest.name,
            "version": self.manifest.version,
            "display_name": self.manifest.display_name,
            "description": self.manifest.description,
            "capabilities": self.manifest.capabilities,
            "tool_count": self.tool_count,
            "skill_count": self.skill_count,
            "missing_tools": self.missing_tools,
            "status": self.status,
            "error": self.error,
            "enabled": self.manifest.enabled,
            "plugin_dir": str(self.plugin_dir),
        }


# ── Skill definitions ────────────────────────────────────────────────────────


@dataclass
class SkillStep:
    """One step in a skill DAG — corresponds 1:1 with a kernel Task."""

    task_id: str
    tool: str
    execution_target: str = "server"
    depends_on: List[str] = field(default_factory=list)
    inputs_from_user: List[str] = field(default_factory=list)
    inputs: Dict[str, Any] = field(default_factory=dict)
    input_bindings: Dict[str, str] = field(default_factory=dict)


@dataclass
class SkillDefinition:
    """A multi-tool workflow declared in a plugin's `skills/*.yaml`."""

    name: str
    description: str = ""
    plugin: str = ""
    trigger_patterns: List[str] = field(default_factory=list)
    required_tools: List[str] = field(default_factory=list)
    steps: List[SkillStep] = field(default_factory=list)
    source_path: Optional[Path] = None

    # Compiled regex patterns (populated after construction)
    _compiled: List[re.Pattern[str]] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        self._compiled = []
        for pattern in self.trigger_patterns:
            try:
                self._compiled.append(re.compile(pattern, re.IGNORECASE))
            except re.error as exc:
                logger.warning(
                    "Skill %r has invalid trigger pattern %r: %s",
                    self.name, pattern, exc,
                )

    @staticmethod
    def from_yaml(yaml_path: Path, plugin: str = "") -> "SkillDefinition":
        import yaml  # local import — only needed when loading skills

        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML in {yaml_path}: {exc}") from exc

        name = str(data.get("name", yaml_path.stem)).strip()
        if not name:
            raise ValueError(f"Skill at {yaml_path} is missing 'name'")

        steps_raw = data.get("steps") or []
        if not isinstance(steps_raw, list) or not steps_raw:
            raise ValueError(f"Skill {name!r} at {yaml_path} has no steps")

        steps: List[SkillStep] = []
        for raw in steps_raw:
            if not isinstance(raw, dict):
                continue
            step_id = str(raw.get("task_id", "")).strip()
            tool = str(raw.get("tool", "")).strip()
            if not step_id or not tool:
                raise ValueError(
                    f"Skill {name!r} step missing task_id/tool in {yaml_path}"
                )
            steps.append(
                SkillStep(
                    task_id=step_id,
                    tool=tool,
                    execution_target=str(raw.get("execution_target", "server")),
                    depends_on=[str(x) for x in (raw.get("depends_on") or [])],
                    inputs_from_user=[str(x) for x in (raw.get("inputs_from_user") or [])],
                    inputs=dict(raw.get("inputs") or {}),
                    input_bindings={
                        str(k): str(v) for k, v in (raw.get("input_bindings") or {}).items()
                    },
                )
            )

        return SkillDefinition(
            name=name,
            description=str(data.get("description", "")),
            plugin=plugin,
            trigger_patterns=[str(p) for p in (data.get("trigger_patterns") or [])],
            required_tools=[str(t) for t in (data.get("required_tools") or [])],
            steps=steps,
            source_path=yaml_path,
        )

    def matches(self, query: str, available_tools: Optional[List[str]] = None) -> bool:
        """Return True if `query` matches any trigger pattern AND every required
        tool is available in the registry."""
        if not query or not self._compiled:
            return False
        if not any(p.search(query) for p in self._compiled):
            return False
        if self.required_tools and available_tools is not None:
            avail = set(available_tools)
            if not all(t in avail for t in self.required_tools):
                return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("_compiled", None)
        d["source_path"] = str(self.source_path) if self.source_path else None
        return d
