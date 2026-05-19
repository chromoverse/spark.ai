"""
SkillEngine — registry + matcher + Task DAG expander.

Skills are pre-defined multi-tool DAGs that bypass LLM planning when the
user query matches a trigger pattern AND all required tools are present.

Lifecycle:
  • plugins discover & register skills via `register_skill_from_path()` or
    `register(skill)` during boot
  • before each LLM SQH call, sqh_service asks `match_skill(query, tools)`
  • on a hit, `expand_to_tasks(skill, user_inputs)` returns a Task[] that
    feeds straight into the orchestrator
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from plugins.models import SkillDefinition, SkillStep

if TYPE_CHECKING:  # pragma: no cover — type-only, no runtime import
    from app.agent.execution_gateway import Task

logger = logging.getLogger(__name__)


class SkillEngine:
    """Holds the registry of loaded skills and resolves them into Task DAGs."""

    def __init__(self) -> None:
        self.skills: Dict[str, SkillDefinition] = {}

    # ── registration ─────────────────────────────────────────────────────

    def register(self, skill: SkillDefinition) -> None:
        if not skill.name:
            return
        if skill.name in self.skills:
            logger.warning(
                "Skill %r already registered (replacing old plugin=%r)",
                skill.name, self.skills[skill.name].plugin,
            )
        self.skills[skill.name] = skill
        logger.info(
            "Registered skill: %s (plugin=%s, %d steps)",
            skill.name, skill.plugin or "?", len(skill.steps),
        )

    def register_skill_from_path(self, yaml_path: Path, plugin: str = "") -> Optional[SkillDefinition]:
        try:
            skill = SkillDefinition.from_yaml(yaml_path, plugin=plugin)
        except Exception as exc:
            logger.error("Failed to load skill from %s: %s", yaml_path, exc)
            return None
        self.register(skill)
        return skill

    def unregister_for_plugin(self, plugin_name: str) -> int:
        """Remove all skills registered by a given plugin. Returns count removed."""
        to_remove = [name for name, s in self.skills.items() if s.plugin == plugin_name]
        for name in to_remove:
            self.skills.pop(name, None)
        return len(to_remove)

    # ── matching ─────────────────────────────────────────────────────────

    def match_skill(
        self, query: str, available_tools: Optional[List[str]] = None,
    ) -> Optional[SkillDefinition]:
        """Return the first skill whose trigger pattern matches the query."""
        if not query:
            return None
        for skill in self.skills.values():
            if skill.matches(query, available_tools):
                logger.info("🧩 Skill match: %r → %s", query[:60], skill.name)
                return skill
        return None

    # ── expansion ────────────────────────────────────────────────────────

    def expand_to_tasks(
        self, skill: SkillDefinition, user_inputs: Optional[Dict[str, Any]] = None,
    ) -> List["Task"]:
        """Concretize a skill into kernel Task objects.

        `user_inputs` carries values pulled from the original query (or PQH
        analysis). Each step's `inputs_from_user` lists keys to copy from
        `user_inputs` into the step's `inputs`. Static `inputs` and
        `input_bindings` declared in the YAML always pass through.
        """
        # Lazy import — the kernel module pulls Settings, so we only touch
        # it once a skill actually fires (during a real request, not at boot
        # of unrelated callers).
        from app.agent.execution_gateway import Task

        user_inputs = user_inputs or {}
        tasks: List[Task] = []
        for step in skill.steps:
            inputs: Dict[str, Any] = dict(step.inputs)
            for key in step.inputs_from_user:
                if key in user_inputs and user_inputs[key] is not None:
                    inputs[key] = user_inputs[key]
            tasks.append(
                Task(
                    task_id=step.task_id,
                    tool=step.tool,
                    execution_target=step.execution_target,  # type: ignore[arg-type]
                    depends_on=list(step.depends_on),
                    inputs=inputs,
                    input_bindings=dict(step.input_bindings),
                )
            )
        return tasks

    # ── inspection ───────────────────────────────────────────────────────

    def list_skills(self) -> List[Dict[str, Any]]:
        return [s.to_dict() for s in self.skills.values()]

    def get_skill(self, name: str) -> Optional[SkillDefinition]:
        return self.skills.get(name)


# ── singleton ────────────────────────────────────────────────────────────────

_instance: Optional[SkillEngine] = None


def get_skill_engine() -> SkillEngine:
    global _instance
    if _instance is None:
        _instance = SkillEngine()
    return _instance


__all__ = ["SkillEngine", "get_skill_engine"]
