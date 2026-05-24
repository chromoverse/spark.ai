"""Adapts MCP tools to the BaseTool interface so the orchestrator treats them uniformly."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.plugins.tools.tool_base import BaseTool, ToolOutput
from app.connectors.mcp.manager import get_mcp_manager

logger = logging.getLogger(__name__)


class MCPToolAdapter(BaseTool):
    """
    Wraps a single MCP tool as a BaseTool.

    Created dynamically when MCP servers are discovered.
    The orchestrator and SQH see these identically to native tools.
    """

    def __init__(self, server_name: str, tool_def: Dict[str, Any]):
        super().__init__()
        self._server_name = server_name
        self._tool_name = tool_def["name"]
        self._tool_def = tool_def

        self.TOOL_DESCRIPTION = tool_def.get("description", "")
        self.EXECUTION_TARGET = "server"
        self.PARAMS_SCHEMA = self._convert_schema(tool_def.get("inputSchema", {}))
        self.OUTPUT_SCHEMA = {"success": {"type": "boolean"}, "data": {"type": "object"}, "error": {"type": "string"}}
        self.SEMANTIC_TAGS = [server_name, self._tool_name]
        self.TOOL_CATEGORY = "external"
        self.EXAMPLES = []
        self.METADATA: Dict[str, Any] = {"source": "mcp", "server": server_name}

    def get_tool_name(self) -> str:
        return self._tool_name

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Execute the tool via MCP JSON-RPC call."""
        try:
            # Strip internal fields before sending to MCP
            clean_inputs = {
                k: v for k, v in inputs.items()
                if not k.startswith("_")
            }
            clean_inputs.pop("user_id", None)

            result = await get_mcp_manager().call_tool(
                self._server_name, self._tool_name, clean_inputs
            )

            if isinstance(result, dict):
                return ToolOutput(success=True, data=result)
            return ToolOutput(success=True, data={"result": result})

        except Exception as exc:
            logger.error("MCP tool %s:%s failed: %s", self._server_name, self._tool_name, exc)
            return ToolOutput(success=False, data={}, error=str(exc))

    @staticmethod
    def _convert_schema(json_schema: Dict[str, Any]) -> Dict[str, Any]:
        """Convert JSON Schema (MCP format) to BaseTool PARAMS_SCHEMA format."""
        params = {}
        properties = json_schema.get("properties", {})
        required = json_schema.get("required", [])

        for name, prop in properties.items():
            params[name] = {
                "type": prop.get("type", "string"),
                "required": name in required,
                "description": prop.get("description", ""),
            }
            if "default" in prop:
                params[name]["default"] = prop["default"]

        return params


def create_mcp_tool_adapters(server_name: str, tools: List[Dict[str, Any]]) -> List[MCPToolAdapter]:
    """Create BaseTool-compatible adapters for all tools from an MCP server."""
    return [MCPToolAdapter(server_name, tool_def) for tool_def in tools]
