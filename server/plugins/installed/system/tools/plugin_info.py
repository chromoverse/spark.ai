"""
plugin_info — example of a plugin-shipped tool.

This file lives entirely INSIDE the system plugin
(server/plugins/installed/system/tools/) and is auto-discovered + auto-
registered by PluginManager at boot. There is NO entry for it in
`tool_registry.json` — its metadata is declared as class attributes below.

It returns a JSON dump of the live PluginManager state, which is useful
for both debugging and answering "what plugins do I have loaded?" via the
assistant.
"""
from __future__ import annotations

from typing import Any, Dict

from app.plugins.tools.tool_base import BaseTool, ToolOutput


class PluginInfoTool(BaseTool):
    # ── Plugin-shipped tool metadata ────────────────────────────────────
    TOOL_DESCRIPTION = (
        "List loaded SparkAI plugins with their tool count, skill count, "
        "version, and capabilities."
    )
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA: Dict[str, Any] = {
        "name": {
            "type": "string",
            "required": False,
            "description": "If provided, return only this plugin's details.",
        },
    }
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "data": {
            "plugins": {"type": "array"},
            "count": {"type": "integer"},
        },
    }
    EXAMPLES = [
        {"user_utterance": "what plugins are loaded"},
        {"user_utterance": "list my plugins"},
        {"user_utterance": "show plugin info"},
    ]
    SEMANTIC_TAGS = ["plugins", "introspection", "system"]

    def get_tool_name(self) -> str:
        return "plugin_info"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        from plugins import get_plugin_manager

        manager = get_plugin_manager()
        name_filter = self.get_input(inputs, "name", None)

        if name_filter:
            state = manager.get_plugin(str(name_filter))
            plugins = [state.to_dict()] if state else []
        else:
            plugins = manager.list_plugins()

        return ToolOutput(
            success=True,
            data={"plugins": plugins, "count": len(plugins)},
        )


__all__ = ["PluginInfoTool"]
