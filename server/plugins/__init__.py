"""
SparkAI plugin system.

Plugins are versioned bundles of tools + skills. Each plugin lives in
`plugins/installed/<name>/` with a `plugin.json` manifest and an optional
`skills/` directory of YAML DAG definitions.

Public entry points:
    from plugins import get_plugin_manager, get_skill_engine
"""
from plugins.manager import PluginManager, get_plugin_manager, DEFAULT_PLUGINS_DIR
from plugins.skills.skill_engine import SkillEngine, get_skill_engine
from plugins.models import PluginManifest, PluginState, SkillDefinition, SkillStep

__all__ = [
    "PluginManager",
    "get_plugin_manager",
    "DEFAULT_PLUGINS_DIR",
    "SkillEngine",
    "get_skill_engine",
    "PluginManifest",
    "PluginState",
    "SkillDefinition",
    "SkillStep",
]
