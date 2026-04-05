from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.plugins.tools.registry_loader import ToolMetadata, get_tool_registry
from app.plugins.tools.tool_index_loader import get_tools_index


class ToolCatalogService:
    def summary(
        self,
        *,
        category: Optional[str] = None,
        execution_target: Optional[str] = None,
    ) -> Dict[str, Any]:
        registry = get_tool_registry()
        index_map = {
            str(tool.get("name", "")).strip(): tool
            for tool in get_tools_index()
            if str(tool.get("name", "")).strip()
        }

        filtered: List[Dict[str, Any]] = []
        for metadata in registry.get_all_tools().values():
            if category and metadata.category != category:
                continue
            if execution_target and metadata.execution_target != execution_target:
                continue

            index_entry = index_map.get(metadata.tool_name, {})
            filtered.append(
                {
                    "name": metadata.tool_name,
                    "description": metadata.description,
                    "category": metadata.category,
                    "execution_target": metadata.execution_target,
                    "example_triggers": index_entry.get(
                        "example_triggers",
                        [metadata.tool_name.replace("_", " ")],
                    ),
                }
            )

        categories = sorted(registry.categories.keys())
        by_target = {
            "server": sum(1 for tool in filtered if tool["execution_target"] == "server"),
            "client": sum(1 for tool in filtered if tool["execution_target"] == "client"),
        }
        return {
            "total_tools": len(filtered),
            "category_filter": category,
            "execution_target_filter": execution_target,
            "categories": categories,
            "by_target": by_target,
            "tools": filtered,
        }

    def detail(self, tool_name: str, *, include_examples: bool = True) -> Optional[Dict[str, Any]]:
        metadata = get_tool_registry().get_tool(tool_name)
        if metadata is None:
            return None
        return self._serialize_tool(metadata, include_examples=include_examples, view="detail")

    def params(self, tool_name: str, *, include_examples: bool = True) -> Optional[Dict[str, Any]]:
        metadata = get_tool_registry().get_tool(tool_name)
        if metadata is None:
            return None
        return self._serialize_tool(metadata, include_examples=include_examples, view="params")

    def query(
        self,
        *,
        tool_name: Optional[str] = None,
        category: Optional[str] = None,
        execution_target: Optional[str] = None,
        view: str = "summary",
        include_examples: bool = True,
    ) -> Dict[str, Any]:
        normalized_view = str(view or "summary").strip().lower()
        if normalized_view == "summary":
            summary = self.summary(category=category, execution_target=execution_target)
            if tool_name:
                summary["tools"] = [tool for tool in summary["tools"] if tool.get("name") == tool_name]
                summary["total_tools"] = len(summary["tools"])
            return summary
        if not tool_name:
            return {"error": "tool_name is required for non-summary views"}
        if normalized_view == "params":
            payload = self.params(tool_name, include_examples=include_examples)
            return payload or {"error": f"Tool '{tool_name}' not found"}
        payload = self.detail(tool_name, include_examples=include_examples)
        return payload or {"error": f"Tool '{tool_name}' not found"}

    @staticmethod
    def _serialize_tool(
        metadata: ToolMetadata,
        *,
        include_examples: bool,
        view: str,
    ) -> Dict[str, Any]:
        base = {
            "tool_name": metadata.tool_name,
            "description": metadata.description,
            "category": metadata.category,
            "execution_target": metadata.execution_target,
            "semantic_tags": metadata.semantic_tags,
        }
        if view == "params":
            base.update(
                {
                    "params_schema": metadata.params_schema,
                    "output_schema": metadata.output_schema,
                    "metadata": metadata.metadata,
                }
            )
        else:
            base.update(
                {
                    "module": metadata.module,
                    "class_name": metadata.class_name,
                    "params_schema": metadata.params_schema,
                    "output_schema": metadata.output_schema,
                    "metadata": metadata.metadata,
                }
            )
        if include_examples:
            base["examples"] = metadata.examples
        return base


_tool_catalog_service: Optional[ToolCatalogService] = None


def get_tool_catalog_service() -> ToolCatalogService:
    global _tool_catalog_service
    if _tool_catalog_service is None:
        _tool_catalog_service = ToolCatalogService()
    return _tool_catalog_service
