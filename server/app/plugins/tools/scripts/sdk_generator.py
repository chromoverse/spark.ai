from __future__ import annotations

import json
import keyword
import logging
from pathlib import Path
from typing import Any

from .runtime_sync import get_runtime_tools_paths

logger = logging.getLogger(__name__)


def _snake_to_pascal(value: str) -> str:
    return "".join(part.capitalize() for part in value.split("_"))


def _safe_identifier(name: str) -> str:
    name = name.replace("-", "_").replace(" ", "_")
    if keyword.iskeyword(name):
        return f"{name}_"
    return name


def _python_type(json_type: str) -> str:
    return {
        "string": "str",
        "integer": "int",
        "number": "float",
        "boolean": "bool",
        "array": "list[Any]",
        "object": "dict[str, Any]",
    }.get(json_type, "Any")


class ToolsSDKGenerator:
    """Generate typed Python SDK wrappers from runtime tool registry."""

    def __init__(self):
        self.paths = get_runtime_tools_paths()

    def generate(self) -> Path:
        registry_path = self.paths.runtime_registry
        if not registry_path.exists():
            raise FileNotFoundError(f"Runtime registry missing: {registry_path}")

        with registry_path.open("r", encoding="utf-8") as f:
            registry = json.load(f)

        out_dir = self.paths.runtime_generated
        out_dir.mkdir(parents=True, exist_ok=True)
        sdk_path = out_dir / "python_sdk.py"

        code = self._build_sdk_code(registry)
        sdk_path.write_text(code, encoding="utf-8")

        logger.info("Generated typed tools SDK: %s", sdk_path)
        return sdk_path

    def _build_sdk_code(self, registry: dict[str, Any]) -> str:
        lines: list[str] = []
        lines.append("from __future__ import annotations")
        lines.append("")
        lines.append("from typing import Any, Protocol, TypedDict")
        lines.append("")
        lines.append("")
        lines.append("class ToolInvoker(Protocol):")
        lines.append("    def __call__(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:")
        lines.append("        ...")
        lines.append("")

        methods: list[str] = []
        categories = registry.get("categories", {})
        for category in categories.values():
            for tool in category.get("tools", []):
                tool_name = tool.get("tool_name")
                if not tool_name:
                    continue

                params_schema = tool.get("params_schema", {})
                output_schema = tool.get("output_schema", {}).get("data", {})

                params_typed = f"{_snake_to_pascal(tool_name)}Params"
                out_typed = f"{_snake_to_pascal(tool_name)}Result"

                lines.extend(self._build_typed_dict(params_typed, params_schema))
                lines.append("")
                lines.extend(self._build_typed_dict(out_typed, output_schema))
                lines.append("")

                method_name = _safe_identifier(tool_name)
                methods.append(
                    f"    def {method_name}(self, params: {params_typed}) -> {out_typed}:\n"
                    f"        return self._invoke(\"{tool_name}\", params)  # type: ignore[return-value]"
                )

        lines.append("class ToolsClient:")
        lines.append("    def __init__(self, invoker: ToolInvoker):")
        lines.append("        self._invoker = invoker")
        lines.append("")
        lines.append("    def _invoke(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:")
        lines.append("        return self._invoker(tool_name, params)")
        lines.append("")
        lines.extend(methods)
        lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    def _build_typed_dict(self, name: str, schema: dict[str, Any]) -> list[str]:
        out: list[str] = [f"class {name}(TypedDict, total=False):"]
        if not schema:
            out.append("    pass")
            return out

        for field_name, field_schema in schema.items():
            py_name = _safe_identifier(field_name)
            field_type = _python_type(str(field_schema.get("type", "object")))
            out.append(f"    {py_name}: {field_type}")
        return out


_sdk_generator: ToolsSDKGenerator | None = None


def get_tools_sdk_generator() -> ToolsSDKGenerator:
    global _sdk_generator
    if _sdk_generator is None:
        _sdk_generator = ToolsSDKGenerator()
    return _sdk_generator

