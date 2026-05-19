"""
tool_tester — interactive helper for running and inspecting tools.

Usage from a Python REPL or a quick script:

    from scripts.tool_tester import list_tools, describe_tool, test_tool, tools

    list_tools()                       # all tools, grouped by category
    list_tools(category="system")      # filter by plugin/category
    describe_tool("app_open")          # pretty-print params + output schema
    await test_tool("app_open", target="chrome")  # run by name
    await tools.app_open(target="chrome")         # run via attribute proxy

Note: tools are async — call from an async context (`await ...`).
The proxy `tools.<name>(...)` is the IDE-friendly entry point. After running
`python -m scripts.tool_tester --gen-stubs` once, your IDE will autocomplete
every tool name and its parameters when typing `tools.`.

Stub generation:

    python -m scripts.tool_tester --gen-stubs

writes `server/scripts/tools.pyi` from the live registry. Re-run whenever
tools are added/removed/renamed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from textwrap import dedent
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Lazy registry access ──────────────────────────────────────────────────
# Importing the tool registry pulls in app.config.Settings, which requires
# environment variables. Defer the import so simple `--help` works without
# a configured environment.


def _registry():
    from app.plugins.tools import get_tool_registry, load_all_tools
    reg = get_tool_registry()
    if not reg.tools:
        reg.load()
    # Make sure instances are loaded so test_tool() can actually run them.
    try:
        load_all_tools()
    except Exception as exc:
        logger.debug("load_all_tools warning: %s", exc)
    return reg


def _instance(tool_name: str):
    from app.plugins.tools import get_tool_for_execution
    return get_tool_for_execution(tool_name)


# ── Public API ────────────────────────────────────────────────────────────


def list_tools(category: Optional[str] = None) -> List[Dict[str, Any]]:
    """List every tool, optionally filtered by plugin/category."""
    reg = _registry()
    rows: List[Dict[str, Any]] = []
    for meta in sorted(reg.tools.values(), key=lambda m: (m.category, m.tool_name)):
        if category and meta.category != category:
            continue
        rows.append({
            "tool_name": meta.tool_name,
            "category": meta.category,
            "execution_target": meta.execution_target,
            "description": meta.description,
            "source": meta.metadata.get("source", "registry"),
        })

    # Pretty-print to stdout for REPL use
    if not rows:
        print(f"(no tools found{f' in category={category!r}' if category else ''})")
    else:
        current = None
        for r in rows:
            if r["category"] != current:
                current = r["category"]
                print(f"\n-- {current} --")
            print(f"  {r['tool_name']:30s}  [{r['execution_target']:6s}]  "
                  f"{r['description'][:70]}")
        print(f"\n{len(rows)} tool(s) shown.")
    return rows


def describe_tool(tool_name: str) -> Dict[str, Any]:
    """Pretty-print a tool's full schema. Returns the metadata dict."""
    reg = _registry()
    meta = reg.get_tool(tool_name)
    if meta is None:
        raise KeyError(f"Tool {tool_name!r} not found. Use list_tools() to see all.")

    info = {
        "tool_name": meta.tool_name,
        "category": meta.category,
        "execution_target": meta.execution_target,
        "description": meta.description,
        "source": meta.metadata.get("source", "registry"),
        "params_schema": meta.params_schema,
        "output_schema": meta.output_schema,
        "examples": meta.examples,
        "semantic_tags": meta.semantic_tags,
    }

    print(f"\n== {meta.tool_name} ==")
    print(f"  category : {meta.category}")
    print(f"  target   : {meta.execution_target}")
    print(f"  source   : {info['source']}")
    print(f"  desc     : {meta.description}")
    if meta.params_schema:
        print("  params   :")
        for p, spec in meta.params_schema.items():
            req = " (required)" if spec.get("required") else ""
            default = f"  [default={spec.get('default')!r}]" if "default" in spec else ""
            print(f"    - {p}: {spec.get('type', 'any')}{req}{default}")
            if spec.get("description"):
                print(f"        {spec['description']}")
    if meta.output_schema:
        out_data = meta.output_schema.get("data") or meta.output_schema
        if out_data:
            print("  output   :")
            for k, spec in out_data.items():
                print(f"    - {k}: {spec.get('type', 'any') if isinstance(spec, dict) else spec}")
    if meta.examples:
        print("  examples :")
        for ex in meta.examples[:3]:
            utterance = ex.get("user_utterance") if isinstance(ex, dict) else ex
            if utterance:
                print(f"    - {utterance!r}")
    print()
    return info


async def test_tool(tool_name: str, **inputs: Any) -> Dict[str, Any]:
    """Execute a tool by name with the given inputs. Returns {success, data, error}.

    Validates that the tool exists, prints what it's doing, runs it, and
    pretty-prints the result. Re-raises nothing — failures are returned in
    the result dict so REPL flow continues.
    """
    reg = _registry()
    meta = reg.get_tool(tool_name)
    if meta is None:
        raise KeyError(f"Tool {tool_name!r} not found. Use list_tools() to see all.")

    instance = _instance(tool_name)
    if instance is None:
        raise RuntimeError(
            f"Tool {tool_name!r} is in the registry but has no live instance. "
            "Try running through the full app boot path."
        )

    print(f"> {tool_name}({', '.join(f'{k}={v!r}' for k, v in inputs.items())})")
    output = await instance.execute(dict(inputs))
    result = {
        "success": output.success,
        "data": output.data,
        "error": output.error,
    }
    icon = "[OK]" if output.success else "[FAIL]"
    print(f"{icon} success={output.success}  error={output.error or '-'}")
    if output.data:
        print("  data:")
        try:
            preview = json.dumps(output.data, indent=2, default=str)
        except TypeError:
            preview = repr(output.data)
        for line in preview.splitlines()[:20]:
            print(f"    {line}")
    print()
    return result


# ── Tool proxy: tools.<name>(**kwargs) ────────────────────────────────────


class _ToolsProxy:
    """`tools.app_open(target="chrome")` → test_tool("app_open", target="chrome")."""

    def __getattr__(self, name: str):
        async def _runner(**kwargs: Any):
            return await test_tool(name, **kwargs)
        _runner.__name__ = name
        _runner.__doc__ = f"Run the {name!r} tool. See describe_tool({name!r}) for params."
        return _runner

    def __dir__(self) -> List[str]:
        try:
            return sorted(_registry().tools.keys())
        except Exception:
            return []


tools = _ToolsProxy()


# ── Stub generation for IDE autocomplete ──────────────────────────────────


_TYPE_MAP = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "array": "list",
    "object": "dict",
}


def _py_type(schema_type: Optional[str]) -> str:
    return _TYPE_MAP.get((schema_type or "").lower(), "Any")


def _format_param(name: str, spec: Dict[str, Any]) -> str:
    py_t = _py_type(spec.get("type"))
    required = bool(spec.get("required"))
    if "default" in spec:
        default = spec["default"]
        return f"{name}: {py_t} = {default!r}"
    if required:
        return f"{name}: {py_t}"
    return f"{name}: {py_t} = ..."


def _generate_stub_text() -> str:
    reg = _registry()
    lines: List[str] = [
        "# AUTO-GENERATED — do not edit by hand.",
        "# Regenerate with: python -m scripts.tool_tester --gen-stubs",
        "from typing import Any, Awaitable, Dict",
        "",
        "ToolResult = Dict[str, Any]",
        "",
        "class _ToolsProxy:",
    ]
    for meta in sorted(reg.tools.values(), key=lambda m: m.tool_name):
        # Sort: required params first, then optional, so we never produce
        # 'non-default after default' in the generated stub signature.
        items = list((meta.params_schema or {}).items())
        items.sort(key=lambda kv: 0 if (isinstance(kv[1], dict) and kv[1].get("required")) else 1)
        params = []
        for p_name, p_spec in items:
            if isinstance(p_spec, dict):
                params.append(_format_param(p_name, p_spec))
        param_str = ", ".join(["self", *params]) if params else "self"
        desc = (meta.description or "").replace('"""', "'''").strip()
        lines.append(f"    async def {meta.tool_name}({param_str}) -> ToolResult:")
        if desc:
            lines.append(f'        """{desc}"""')
        lines.append("        ...")
    lines.append("")
    lines.append("tools: _ToolsProxy")
    lines.append("")
    return "\n".join(lines)


def write_stub(path: Optional[Path] = None) -> Path:
    """Write the IDE stub. Returns the resulting path."""
    target = path or Path(__file__).resolve().parent / "tools.pyi"
    target.parent.mkdir(parents=True, exist_ok=True)
    text = _generate_stub_text()
    target.write_text(text, encoding="utf-8")
    print(f"Wrote {target}  ({text.count('async def') - 1} tools)")
    return target


# ── CLI ───────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="SparkAI tool tester / introspector.")
    sub = p.add_subparsers(dest="cmd")

    sp_list = sub.add_parser("list", help="list tools")
    sp_list.add_argument("--category", default=None)

    sp_desc = sub.add_parser("describe", help="describe one tool")
    sp_desc.add_argument("tool_name")

    sp_run = sub.add_parser("run", help="run one tool with --inputs '{...}'")
    sp_run.add_argument("tool_name")
    sp_run.add_argument("--inputs", default="{}",
                         help="JSON object of inputs, e.g. '{\"target\":\"chrome\"}'")

    p.add_argument("--gen-stubs", action="store_true",
                    help="Regenerate scripts/tools.pyi for IDE autocomplete and exit.")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.gen_stubs:
        write_stub()
        return 0

    if args.cmd == "list":
        list_tools(category=args.category)
    elif args.cmd == "describe":
        describe_tool(args.tool_name)
    elif args.cmd == "run":
        try:
            inputs = json.loads(args.inputs)
        except json.JSONDecodeError as exc:
            print(f"--inputs must be JSON: {exc}", file=sys.stderr)
            return 2
        if not isinstance(inputs, dict):
            print("--inputs must be a JSON object.", file=sys.stderr)
            return 2
        asyncio.run(test_tool(args.tool_name, **inputs))
    else:
        _build_parser().print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
