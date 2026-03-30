# SparkAI Tools Developer Manual

This manual explains how to add runtime tools for SparkAI.
Runtime source of truth is AppData `tools_plugin` (not `app.agent.shared`).

## 1. Required layout

Tool code in this folder is seeded to:
- `AppData/Local/SparkAI/tools_plugin`

Runtime layout:
- `tools_plugin/manifest.json`
- `tools_plugin/registry/tool_registry.json`
- `tools_plugin/registry/tool_index.json`
- `tools_plugin/tools/...`
- `tools_plugin/automation/...`
- `tools_plugin/utils/...`

Add implementation under one category package inside `tools/`:
- `system/`
- `file_system/`
- `web/`
- `ai/`
- `messaging/`

Each tool class must inherit `BaseTool` and implement:
- `get_tool_name(self) -> str`
- `_execute(self, inputs: dict[str, Any]) -> ToolOutput`

## 2. Register schema

Add or update the tool entry in:
- `tools_plugin/registry/tool_registry.json`

Required fields:
- `tool_name`
- `description`
- `execution_target`
- `params_schema`
- `output_schema`
- `metadata`

## 3. Register plugin mapping

Update `manifest.json` in this folder and add a plugin entry:

```json
{
  "tool_name": "my_tool",
  "module": "system.my_module",
  "class_name": "MyTool"
}
```

Rules:
- `module` is import path relative to runtime `tools/` root.
- `class_name` must match the Python class.
- `tool_name` must exactly match `get_tool_name()`.

## 4. Approval and timeout policy

Use `metadata` in registry to set defaults:
- `default_requires_approval`
- `default_approval_question`
- `default_timeout_ms`

Destructive tools must set approval defaults.

## 5. Validate changes

Run the tool tester:

```bash
python tool_tester.py
```

Expected checks:
- Manifest validity
- Tool registry compatibility
- Plugin import/class loading
- `tool_name` match with implementation

## 6. Versioning

If you add/remove tool plugins, bump `manifest.json` version.
Runtime sync compares seed version vs AppData runtime version.

## 7. Runtime sync and SDK

On server startup:
1. Seed folders from this external `tools_plugin/` sync to `AppData/Local/SparkAI/tools_plugin`.
2. Runtime tools load from `tools_plugin.tools.*`.
3. Typed SDK is generated at `.../tools_plugin/generated/python_sdk.py`.
