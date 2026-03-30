# SparkAI Tools Runtime

`server/tools` is the runtime source of truth for SparkAI tools.

## Layout
- `manifest.json`
- `registry/tool_registry.json`
- `registry/tool_index.json`
- `tools/...`
- `automation/...`
- `utils/...`
- `tool_tester.py`

## Local Development
- Use the main server environment. There is no separate tools virtualenv.
- Run the tester from the `server/` directory:
  - `python -m tools.tool_tester --list`
  - `python -m tools.tool_tester system_info "{}"`
  - `python -m tools.tool_tester --tool message_send --inputs "{\"contact\":\"Rajesh Vaiya\",\"message\":\"hello\"}"`
  - `python -m tools.tool_tester --import tools.messaging.message_send:MessageSendTool --inputs "{\"contact\":\"Rajesh Vaiya\",\"message\":\"hello\"}"`

## Runtime Model
- The server loads tools directly from the `tools.*` package.
- The registry and manifest are read from this folder.
