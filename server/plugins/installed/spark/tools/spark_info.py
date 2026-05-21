"""spark_info — answers any question about Spark's plugins, tools, skills, and categories.

This is the go-to tool when the user asks:
- How many tools / what tools / list tools
- What plugins are loaded / plugin details
- What categories exist / tools in a category
- What skills are available
- Any introspection about Spark's capabilities
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.plugins.tools.tool_base import BaseTool, ToolOutput


class SparkInfoTool(BaseTool):
    """Answer any question about Spark's plugins, tools, skills, and categories."""

    TOOL_DESCRIPTION = (
        "Answer questions about Spark's capabilities: total tool count, "
        "list tools by name/category/plugin, list plugins, list skills, "
        "list categories, or explain what a specific tool does. "
        "Use this for ANY introspection question about what Spark can do."
    )
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA: Dict[str, Any] = {
        "query": {
            "type": "string",
            "required": True,
            "description": "The introspection question: 'how many tools', 'list plugins', 'tools in system_control', 'what can you do', etc.",
        },
    }
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {
            "answer": {"type": "string"},
            "details": {"type": "object"},
        },
        "error": {"type": "string"},
    }
    EXAMPLES = [
        {"user_utterance": "how many tools do you have", "inputs": {"query": "how many tools"}},
        {"user_utterance": "what plugins are loaded", "inputs": {"query": "list plugins"}},
        {"user_utterance": "what tools are in system_control category", "inputs": {"query": "tools in system_control"}},
        {"user_utterance": "what can you do", "inputs": {"query": "capabilities overview"}},
        {"user_utterance": "list all your skills", "inputs": {"query": "list skills"}},
        {"user_utterance": "what categories do you have", "inputs": {"query": "list categories"}},
    ]
    SEMANTIC_TAGS = ["spark", "info", "tools", "plugins", "skills", "categories", "introspection", "capabilities"]
    TOOL_CATEGORY = "spark_internal"
    METADATA: Dict[str, Any] = {"summary_tts": True}

    def get_tool_name(self) -> str:
        return "spark_info"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        query = str(self.get_input(inputs, "query", "")).strip().lower()
        if not query:
            return ToolOutput(success=False, data={}, error="query is required")

        # Gather all system knowledge
        info = self._gather_info()

        # Route query to appropriate response
        if any(k in query for k in ["how many tool", "tool count", "total tool"]):
            return self._answer_tool_count(info)
        elif any(k in query for k in ["list plugin", "what plugin", "loaded plugin", "plugins"]):
            return self._answer_plugins(info)
        elif any(k in query for k in ["list categor", "what categor", "categories"]):
            return self._answer_categories(info)
        elif any(k in query for k in ["list skill", "what skill", "skills"]):
            return self._answer_skills(info)
        elif any(k in query for k in ["tools in ", "category "]):
            # Extract category name
            for cat in info["categories"]:
                if cat in query:
                    return self._answer_tools_in_category(info, cat)
            return self._answer_tool_count(info)
        elif any(k in query for k in ["what can", "capabilit", "overview", "what do you"]):
            return self._answer_overview(info)
        elif any(k in query for k in ["list tool", "what tool", "all tool", "tool name"]):
            return self._answer_all_tools(info)
        else:
            # Default: give overview
            return self._answer_overview(info)

    def _gather_info(self) -> Dict[str, Any]:
        from app.plugins.tools.registry_loader import get_tool_registry
        from app.prompts.tool_categories import get_all_categories, CATEGORY_TO_TOOLS

        registry = get_tool_registry()
        categories = get_all_categories()

        # Get plugin info
        plugins: List[Dict] = []
        try:
            from plugins import get_plugin_manager
            plugins = get_plugin_manager().list_plugins()
        except Exception:
            pass

        # Get skills
        skills: List[str] = []
        for p in plugins:
            for s in p.get("skills", []):
                skills.append(f"{s.get('name', '?')} ({p.get('name', '?')})")

        # Tools per category
        tools_by_cat = {}
        for cat, tool_names in CATEGORY_TO_TOOLS.items():
            tools_by_cat[cat] = tool_names

        return {
            "total_tools": len(registry.tools),
            "server_tools": len(registry.server_tools),
            "client_tools": len(registry.client_tools),
            "categories": categories,
            "tools_by_category": tools_by_cat,
            "plugins": plugins,
            "skills": skills,
            "all_tool_names": sorted(registry.tools.keys()),
        }

    def _answer_tool_count(self, info: Dict) -> ToolOutput:
        return ToolOutput(success=True, data={
            "answer": f"Spark has {info['total_tools']} tools across {len(info['categories'])} categories. {info['server_tools']} run server-side, {info['client_tools']} run client-side.",
            "details": {"total": info["total_tools"], "server": info["server_tools"], "client": info["client_tools"], "categories": len(info["categories"])},
        })

    def _answer_plugins(self, info: Dict) -> ToolOutput:
        plugin_lines = []
        for p in info["plugins"]:
            name = p.get("name", "?")
            tools = p.get("tools_registered", p.get("tool_count", 0))
            skills = len(p.get("skills", []))
            plugin_lines.append(f"• {name}: {tools} tools, {skills} skills")
        answer = f"{len(info['plugins'])} plugins loaded:\n" + "\n".join(plugin_lines)
        return ToolOutput(success=True, data={"answer": answer, "details": {"plugins": info["plugins"], "count": len(info["plugins"])}})

    def _answer_categories(self, info: Dict) -> ToolOutput:
        cat_lines = []
        for name, desc in info["categories"].items():
            count = len(info["tools_by_category"].get(name, []))
            cat_lines.append(f"• {name} ({count} tools): {desc}")
        answer = f"{len(info['categories'])} categories:\n" + "\n".join(cat_lines)
        return ToolOutput(success=True, data={"answer": answer, "details": {"categories": info["categories"]}})

    def _answer_skills(self, info: Dict) -> ToolOutput:
        if not info["skills"]:
            return ToolOutput(success=True, data={"answer": "No skills currently loaded.", "details": {"skills": []}})
        answer = f"{len(info['skills'])} skills:\n" + "\n".join(f"• {s}" for s in info["skills"])
        return ToolOutput(success=True, data={"answer": answer, "details": {"skills": info["skills"], "count": len(info["skills"])}})

    def _answer_tools_in_category(self, info: Dict, category: str) -> ToolOutput:
        tools = info["tools_by_category"].get(category, [])
        answer = f"{len(tools)} tools in '{category}':\n" + ", ".join(tools)
        return ToolOutput(success=True, data={"answer": answer, "details": {"category": category, "tools": tools, "count": len(tools)}})

    def _answer_all_tools(self, info: Dict) -> ToolOutput:
        # Group by category for readability
        lines = []
        for cat, tools in sorted(info["tools_by_category"].items()):
            lines.append(f"\n[{cat}] ({len(tools)} tools): {', '.join(sorted(tools))}")
        answer = f"All {info['total_tools']} tools:" + "".join(lines)
        return ToolOutput(success=True, data={"answer": answer, "details": {"total": info["total_tools"], "tools_by_category": info["tools_by_category"]}})

    def _answer_overview(self, info: Dict) -> ToolOutput:
        answer = (
            f"Spark has {info['total_tools']} tools across {len(info['categories'])} categories, "
            f"powered by {len(info['plugins'])} plugins with {len(info['skills'])} skills.\n\n"
            f"Categories: {', '.join(info['categories'].keys())}"
        )
        return ToolOutput(success=True, data={"answer": answer, "details": {"total_tools": info["total_tools"], "categories": len(info["categories"]), "plugins": len(info["plugins"]), "skills": len(info["skills"])}})


__all__ = ["SparkInfoTool"]
