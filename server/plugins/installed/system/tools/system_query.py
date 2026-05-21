"""System query tools."""
from __future__ import annotations
from datetime import datetime
from typing import Any, Dict
from app.plugins.tools.tool_base import BaseTool, ToolOutput


class SystemQueryTool(BaseTool):
    """Answer arbitrary system information questions."""

    TOOL_DESCRIPTION = "Answer arbitrary system questions (CPU temp, GPU, disk health, installed software, services, uptime, env vars)"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA: Dict[str, Any] = {"query": {"type": "string", "required": True, "description": "Natural language system question"}}
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {"query": {"type": "string"}, "data": {"type": "object"}, "source": {"type": "string"}, "timestamp": {"type": "string"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "what's my CPU temperature", "inputs": {"query": "CPU temperature"}}]
    SEMANTIC_TAGS = ["system", "query", "info", "hardware"]
    TOOL_CATEGORY = "system_control"

    def get_tool_name(self) -> str:
        return "system_query"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        query = str(self.get_input(inputs, "query", "")).strip()
        if not query:
            return ToolOutput(success=False, data={}, error="query is required")
        try:
            from app.agent.runtime.environment_context_service import get_environment_context_service
            result = await get_environment_context_service().query_system(query)
            return ToolOutput(success=True, data={"query": query, "data": result, "source": result.get("source", "system_query"), "timestamp": datetime.now().isoformat()})
        except Exception as e:
            return ToolOutput(success=False, data={}, error=str(e))


class SystemEnvSnapshotTool(BaseTool):
    """Get a compact snapshot of the current environment."""

    TOOL_DESCRIPTION = "Get a compact snapshot of the current environment (windows, processes, specs)"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA: Dict[str, Any] = {
        "working_dir": {"type": "string", "required": False},
        "include_display": {"type": "boolean", "required": False, "default": False},
        "include_network": {"type": "boolean", "required": False, "default": False},
    }
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {"snapshot": {"type": "object"}, "compact": {"type": "string"}, "timestamp": {"type": "string"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "what's running on my system right now"}]
    SEMANTIC_TAGS = ["system", "environment", "snapshot", "processes"]
    TOOL_CATEGORY = "system_control"

    def get_tool_name(self) -> str:
        return "system_env_snapshot"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            from app.agent.runtime.environment_context_service import get_environment_context_service
            service = get_environment_context_service()
            working_dir = self.get_input(inputs, "working_dir", None)
            include_display = bool(self.get_input(inputs, "include_display", False))
            include_network = bool(self.get_input(inputs, "include_network", False))
            snapshot = await service.get_snapshot(include_windows=True, include_processes=True, include_system=True, include_display=include_display, include_network=include_network, working_dir=working_dir)
            compact = await service.get_compact_context(working_dir=working_dir)
            return ToolOutput(success=True, data={"snapshot": snapshot, "compact": compact, "timestamp": datetime.now().isoformat()})
        except Exception as e:
            return ToolOutput(success=False, data={}, error=str(e))


__all__ = ["SystemQueryTool", "SystemEnvSnapshotTool"]
