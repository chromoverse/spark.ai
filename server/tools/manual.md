# SparkAI Tools Developer Manual

`server/tools` is the runtime source of truth for SparkAI tools.

This file is the short overview. The step-by-step authoring workflow now lives
in [`HOW_TO_ADD_TOOL.md`](HOW_TO_ADD_TOOL.md).

## Runtime layout

- `server/tools/registry/tool_registry.json`: canonical authored registry
- `server/tools/registry/tool_index.json`: generated slim index for runtime lookups
- `server/tools/manifest.json`: generated compatibility manifest
- `server/tools/tools/...`: tool implementations
- `server/tools/utils/...`: shared helpers used by tools
- `server/tools/automation/...`: automation-specific modules

## High-level rules

- Implement runtime tools under `tools.tools.*`.
- Every tool class must inherit `tools.tools.base.BaseTool`.
- `get_tool_name()` must exactly match the registry entry.
- Tool class docstrings should include concise `Inputs:` and `Outputs:` sections.
- Destructive tools should define approval defaults in the registry metadata.

## Generated files

Do not hand-edit `manifest.json` or `registry/tool_index.json`.

After changing `tool_registry.json`, regenerate helper files from `server/`:

```bash
python scripts/sync_index_manifest_with_registry.py
```

Validate without rewriting:

```bash
python scripts/sync_index_manifest_with_registry.py --check
```

## Local validation

Run the tool tester from `server/`:

```bash
python -m tools.tool_tester --list
python -m tools.tool_tester --tool system_info --inputs "{}"
```

For the full add/change workflow, use [`HOW_TO_ADD_TOOL.md`](HOW_TO_ADD_TOOL.md).
