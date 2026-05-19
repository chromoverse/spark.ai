"""System deep-info query tool.

system_query:
- Purpose: answer arbitrary system questions that don't have a dedicated tool.
  Handles CPU temp, GPU info, disk health, installed software, services,
  uptime, environment variables, and more.
- Uses EnvironmentContextService for actual data gathering.
- Inputs: query (required) — natural language system question
- Outputs: query, data (dict), source, timestamp

system_env_snapshot:
- Purpose: get a compact snapshot of the current environment (windows, processes, specs).
- Inputs: none
- Outputs: snapshot data
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from ..base import BaseTool, ToolOutput


class SystemQueryTool(BaseTool):
    """Answer arbitrary system information questions.

    When the user asks about CPU temperature, GPU specs, disk health,
    installed programs, running services, environment variables, uptime,
    or any system detail that doesn't have a dedicated tool — this tool
    handles it by running the appropriate OS-level queries.

    Inputs:
    - query (string, required): natural language system question

    Outputs:
    - query (string): the original question
    - data (object): structured answer data
    - source (string): which subsystem answered
    - timestamp (string): ISO timestamp
    """

    def get_tool_name(self) -> str:
        return "system_query"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        query = str(self.get_input(inputs, "query", "")).strip()
        if not query:
            return ToolOutput(success=False, data={}, error="query is required")

        try:
            from app.agent.runtime.environment_context_service import (
                get_environment_context_service,
            )

            service = get_environment_context_service()
            result = await service.query_system(query)

            return ToolOutput(
                success=True,
                data={
                    "query": query,
                    "data": result,
                    "source": result.get("source", "system_query"),
                    "timestamp": datetime.now().isoformat(),
                },
            )
        except Exception as e:
            self.logger.error("system_query failed: %s", e, exc_info=True)
            return ToolOutput(success=False, data={}, error=str(e))


class SystemEnvSnapshotTool(BaseTool):
    """Get a compact snapshot of the current environment.

    Returns active windows, key processes, system specs, and optionally
    the working directory tree — useful for understanding what's happening
    on screen and which apps are running.

    Inputs:
    - working_dir (string, optional): directory to include in snapshot
    - include_display (boolean, optional): include display/monitor info
    - include_network (boolean, optional): include network adapter info

    Outputs:
    - snapshot (object): full environment snapshot
    - compact (string): human-readable summary
    - timestamp (string): ISO timestamp
    """

    def get_tool_name(self) -> str:
        return "system_env_snapshot"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            from app.agent.runtime.environment_context_service import (
                get_environment_context_service,
            )

            service = get_environment_context_service()
            working_dir = self.get_input(inputs, "working_dir", None)
            include_display = bool(self.get_input(inputs, "include_display", False))
            include_network = bool(self.get_input(inputs, "include_network", False))

            snapshot = await service.get_snapshot(
                include_windows=True,
                include_processes=True,
                include_system=True,
                include_display=include_display,
                include_network=include_network,
                working_dir=working_dir,
            )

            compact = await service.get_compact_context(working_dir=working_dir)

            return ToolOutput(
                success=True,
                data={
                    "snapshot": snapshot,
                    "compact": compact,
                    "timestamp": datetime.now().isoformat(),
                },
            )
        except Exception as e:
            self.logger.error("system_env_snapshot failed: %s", e, exc_info=True)
            return ToolOutput(success=False, data={}, error=str(e))


__all__ = ["SystemQueryTool", "SystemEnvSnapshotTool"]
