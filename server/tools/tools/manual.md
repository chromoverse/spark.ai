# SparkAI Tools Developer Manual

This manual explains how to add runtime tools for SparkAI. The source of truth is `server/tools`.

## 1. Required layout

Runtime layout:
- `server/tools/manifest.json`
- `server/tools/registry/tool_registry.json`
- `server/tools/registry/tool_index.json`
- `server/tools/tools/...`
- `server/tools/automation/...`
- `server/tools/utils/...`

Add implementation under one category package inside `server/tools/tools/`:
- `system/`
- `file_system/`
- `web/`
- `ai/`
- `messaging/`

Each tool class must inherit `tools.tools.base.BaseTool` and implement:
- `get_tool_name(self) -> str`
- `_execute(self, inputs: dict[str, Any]) -> ToolOutput`

## 2. Register schema

Add or update the tool entry in:
- `server/tools/registry/tool_registry.json`

Required fields:
- `tool_name`
- `description`
- `execution_target`
- `params_schema`
- `output_schema`
- `metadata`

## 3. Register plugin mapping

Update `server/tools/manifest.json` and add a plugin entry:

```json
{
  "tool_name": "my_tool",
  "module": "system.my_module",
  "class_name": "MyTool"
}
```

Rules:
- `module` is import path relative to `server/tools/tools/`.
- `class_name` must match the Python class.
- `tool_name` must exactly match `get_tool_name()`.

## 4. Approval and timeout policy

Use `metadata` in registry to set defaults:
- `default_requires_approval`
- `default_approval_question`
- `default_timeout_ms`

Destructive tools must set approval defaults.

## 5. Validate changes

Run the tool tester from the `server/` directory:

```bash
python -m tools.tool_tester --list
python -m tools.tool_tester --tool my_tool --inputs "{}"
```

Expected checks:
- Manifest validity
- Tool registry compatibility
- Plugin import/class loading
- `tool_name` match with implementation

## 6. Versioning

If you add/remove tool plugins, bump `manifest.json` version.

## 7. Loader

On server startup:
1. The server reads the manifest and registry from `server/tools`.
2. Runtime tools load from `tools.tools.*`.
