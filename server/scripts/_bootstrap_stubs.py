"""One-off: build tools.pyi from the JSON registry without booting the app."""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REG = REPO / "server" / "tools" / "registry" / "tool_registry.json"
OUT = REPO / "server" / "scripts" / "tools.pyi"

TYPE_MAP = {
    "string": "str", "integer": "int", "number": "float",
    "boolean": "bool", "array": "list", "object": "dict",
}


def py_type(t):
    return TYPE_MAP.get((t or "").lower(), "Any")


def fmt_param(name, spec):
    py_t = py_type(spec.get("type"))
    if "default" in spec:
        return f"{name}: {py_t} = {spec['default']!r}"
    if spec.get("required"):
        return f"{name}: {py_t}"
    return f"{name}: {py_t} = ..."


reg = json.loads(REG.read_text(encoding="utf-8"))

tools_sorted = []
for cat, info in reg["categories"].items():
    for t in info["tools"]:
        tools_sorted.append(t)
tools_sorted.sort(key=lambda t: t["tool_name"])

lines = [
    "# AUTO-GENERATED — do not edit by hand.",
    "# Regenerate with: python -m scripts.tool_tester --gen-stubs",
    "from typing import Any, Dict",
    "",
    "ToolResult = Dict[str, Any]",
    "",
    "class _ToolsProxy:",
]

for t in tools_sorted:
    name = t["tool_name"]
    items = list((t.get("params_schema") or {}).items())
    # Required params first so the stub never emits a non-default-after-default sig.
    items.sort(key=lambda kv: 0 if (isinstance(kv[1], dict) and kv[1].get("required")) else 1)
    params = []
    for p_name, p_spec in items:
        if isinstance(p_spec, dict):
            params.append(fmt_param(p_name, p_spec))
    param_str = ", ".join(["self", *params]) if params else "self"
    desc = (t.get("description") or "").replace('"""', "'''").strip()
    lines.append(f"    async def {name}({param_str}) -> ToolResult:")
    if desc:
        lines.append(f'        """{desc}"""')
    lines.append("        ...")

lines.append("")
lines.append("tools: _ToolsProxy")
lines.append("")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"Wrote {OUT}  ({len(tools_sorted)} tools)")
