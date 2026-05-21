"""Tool registry introspection tool.

tool_catalog:
- Purpose: answer inventory, detail, and parameter questions from the canonical registry.
- Inputs: tool_name?, category?, execution_target?, view?, include_examples?
- Outputs: summary counts or a normalized detail/params payload for matching tools.
"""

from __future__ import annotations

from typing import Any, Dict

from app.plugins.tools.catalog_service import get_tool_catalog_service

from app.plugins.tools.tool_base import BaseTool, ToolOutput


class ToolCatalogTool(BaseTool):
    """Expose registry-backed tool summary/detail/params views at runtime.

    Inputs:
    - tool_name (string, optional): exact tool name for detail/params lookup
    - category (string, optional): registry category filter for summary view
    - execution_target (string, optional): target filter, usually "server" or "client"
    - view (string, optional): "summary", "detail", or "params"
    - include_examples (boolean, optional): include registry examples when detail/params are returned

    Outputs:
    - view (string): normalized response view
    - total_tools (integer): number of matching tools
    - categories (array): known registry categories for summary responses
    - by_target (object): summary counts grouped by execution target
    - tools (array): matching summary entries when view="summary"
    - tool (object): normalized tool payload when view is "detail" or "params"
    """

    # ── Plugin-shipped tool metadata ────────────────────────────────────
    TOOL_DESCRIPTION = "Inspect the canonical tool catalog, schemas, and examples"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA: Dict[str, Any] = {
        "tool_name": {"type": "string", "required": False},
        "category": {"type": "string", "required": False},
        "execution_target": {"type": "string", "required": False},
        "view": {"type": "string", "required": False, "default": "summary"},
        "include_examples": {"type": "boolean", "required": False, "default": True},
    }
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {
            "view": {"type": "string"},
            "total_tools": {"type": "integer"},
            "categories": {"type": "array"},
            "by_target": {"type": "object"},
            "tools": {"type": "array"},
            "tool": {"type": "object"},
        },
        "error": {"type": "string"},
    }
    EXAMPLES = [
        {"user_utterance": "how many tools do you have", "inputs": {"view": "summary"}, "notes": "No category filter - returns ALL tools"},
        {"user_utterance": "what tools are available", "inputs": {"view": "summary"}, "notes": "No category filter - returns ALL tools"},
        {"user_utterance": "what is app_open params", "inputs": {"tool_name": "app_open", "view": "params"}},
        {"user_utterance": "show me system control tools", "inputs": {"category": "system_control", "view": "summary"}},
    ]
    SEMANTIC_TAGS = ["tools", "registry", "schemas", "introspection"]
    TOOL_CATEGORY = "spark_internal"

    def get_tool_name(self) -> str:
        return "tool_catalog"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        tool_name = self.get_input(inputs, "tool_name", None)
        category = self.get_input(inputs, "category", None)
        execution_target = self.get_input(inputs, "execution_target", None)
        view = self.get_input(inputs, "view", "summary")
        include_examples = bool(self.get_input(inputs, "include_examples", True))

        payload = get_tool_catalog_service().query(
            tool_name=tool_name,
            category=category,
            execution_target=execution_target,
            view=view,
            include_examples=include_examples,
        )
        if payload.get("error"):
            return ToolOutput(success=False, data={}, error=str(payload["error"]))
        normalized = {
            "view": str(view or "summary"),
            "total_tools": int(payload.get("total_tools", 1 if payload.get("tool") or payload.get("tool_name") else 0)),
            "categories": payload.get("categories", []),
            "by_target": payload.get("by_target", {}),
            "tools": payload.get("tools", []),
            "tool": payload.get("tool", payload if payload.get("tool_name") else {}),
        }
        return ToolOutput(success=True, data=normalized)


__all__ = ["ToolCatalogTool"]
