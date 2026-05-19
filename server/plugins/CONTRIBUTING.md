# Contributing to SparkAI Plugins

This guide walks you through adding a new plugin from scratch.

## Quick start (5 minutes)

```bash
# 1. Create your plugin folder
mkdir -p server/plugins/installed/my_plugin/tools
mkdir -p server/plugins/installed/my_plugin/skills

# 2. Write plugin.json (see template below)
# 3. Drop a .py tool file into tools/
# 4. Restart the server — done
```

## Plugin manifest template

Create `server/plugins/installed/<name>/plugin.json`:

```json
{
  "name": "my_plugin",
  "version": "1.0.0",
  "display_name": "My Plugin",
  "description": "What this plugin does in one sentence.",
  "author": "your-github-handle",
  "capabilities": ["capability_1", "capability_2"],
  "tools": [],
  "skills": [],
  "dependencies": [],
  "config_schema": {},
  "enabled": true
}
```

## Writing a tool

Create `server/plugins/installed/<name>/tools/my_tool.py`:

```python
from app.plugins.tools.tool_base import BaseTool, ToolOutput


class MyTool(BaseTool):
    TOOL_DESCRIPTION = "One-line description shown to the LLM."
    EXECUTION_TARGET = "server"  # or "client"
    PARAMS_SCHEMA = {
        "input_name": {
            "type": "string",
            "required": True,
            "description": "What this input is for.",
        },
    }
    OUTPUT_SCHEMA = {
        "data": {
            "result": {"type": "string"},
        }
    }
    EXAMPLES = [
        {"user_utterance": "do the thing with X"},
    ]
    SEMANTIC_TAGS = ["my_plugin", "action"]

    def get_tool_name(self) -> str:
        return "my_tool"  # must be globally unique

    async def _execute(self, inputs):
        value = self.get_input(inputs, "input_name", "")
        # ... do work ...
        return ToolOutput(success=True, data={"result": f"Done: {value}"})
```

That's it. The plugin manager auto-discovers it at boot.

## Writing a skill (optional)

Create `server/plugins/installed/<name>/skills/my_recipe.yaml`:

```yaml
name: my_recipe
description: "What this multi-step workflow does"
plugin: my_plugin
required_tools:
  - tool_a
  - tool_b
trigger_patterns:
  - "do X and then Y"
  - "X followed by Y"
steps:
  - task_id: step_1
    tool: tool_a
    execution_target: server
    inputs_from_user:
      - query
  - task_id: step_2
    tool: tool_b
    execution_target: server
    depends_on:
      - step_1
    input_bindings:
      data: "$.step_1.data.result"
```

Reference it in `plugin.json`:
```json
"skills": [{"name": "my_recipe", "file": "skills/my_recipe.yaml"}]
```

## Skill modes

| Mode | When | What happens |
|---|---|---|
| Full bypass | No step has `inputs_from_user` | LLM is skipped entirely — fastest |
| Template hint | Any step has `inputs_from_user` | LLM runs but only fills inputs — structure is locked |

## Testing your tool

```bash
cd server

# List all tools (confirm yours appears)
python -m scripts.tool_tester list --category my_plugin

# Inspect schema
python -m scripts.tool_tester describe my_tool

# Run it
python -m scripts.tool_tester run my_tool --inputs '{"input_name": "hello"}'

# Regenerate IDE stubs
python -m scripts.tool_tester --gen-stubs
```

## Checklist before submitting

- [ ] `plugin.json` has a unique `name`
- [ ] Every tool's `get_tool_name()` returns a globally unique string
- [ ] `PARAMS_SCHEMA` marks required fields with `"required": True`
- [ ] `OUTPUT_SCHEMA` declares all fields the tool returns in `data`
- [ ] `EXAMPLES` has at least one `user_utterance` (helps PQH pick the tool)
- [ ] Tool handles errors gracefully (returns `ToolOutput(success=False, ...)`)
- [ ] Skills have at least one `trigger_patterns` regex
- [ ] Skills list all tools in `required_tools`
- [ ] `python -m scripts.tool_tester describe <tool>` works
- [ ] `python -m scripts.tool_tester run <tool> --inputs '{...}'` succeeds

## Architecture overview

```
User query
  → PQH (picks tool names from tool_index — your tool appears here automatically)
  → SQH:
      ├── SkillEngine checks if a skill matches
      │     ├── Full bypass: expand YAML → Task[] → orchestrator
      │     └── Template: inject structure into LLM prompt → LLM fills inputs
      └── No skill: LLM generates full plan
  → Orchestrator (resolves DAG dependencies)
  → ExecutionEngine
      → ToolInstanceRegistry.get("my_tool") → BaseTool.execute()
  → KernelEvent emitted → ActivityLog records it
```

## Task tracking guarantees

Every task goes through these states:
```
pending → running → completed
                  → failed
pending → emitted (client task) → completed/failed (via ack)
pending → waiting (needs approval) → approved → running → ...
                                   → failed (timeout 180s)
```

- **No task is lost**: emitted tasks timeout after 120s, waiting tasks after 180s
- **Every transition is logged** via KernelEventBus → ActivityLog (SQLite FTS5)
- **Exceptions are caught**: unhandled errors in `_execute()` → `ToolOutput(success=False)`

## File structure

```
server/plugins/installed/my_plugin/
├── plugin.json          ← manifest (required)
├── tools/               ← auto-discovered Python files
│   └── my_tool.py
└── skills/              ← YAML DAGs (optional)
    └── my_recipe.yaml
```
