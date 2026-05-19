# SparkAI Plugin System

This document explains how the plugin system works end-to-end, who talks to whom, and how to contribute new plugins (vision, hearing, anything else).

---

## 1. Mental model

A **plugin** is a self-contained capability bundle. Each plugin owns:

- **Tools** — atomic, callable units (e.g. `app_open`, `screenshot_capture`, `web_search`). One tool = one verb.
- **Skills** *(optional)* — pre-defined multi-tool DAGs that bypass the LLM planner for known recipes (e.g. "create file then open it").
- **Capabilities** — high-level tags advertising what the plugin enables (`shell`, `vision`, `hearing`, `email_send`, …).
- **Config schema** *(optional)* — knobs the plugin exposes for runtime configuration.

Tools live in `server/tools/tools/<category>/` (legacy) **or** inside the plugin folder at `installed/<plugin>/tools/` (new layout). Both work simultaneously.

---

## 2. End-to-end request flow

```
User voice/text
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  PQH  (Primary Query Handler — chat_service.py)             │
│  • Decides if a tool is needed                              │
│  • Picks tool name(s) from registry                         │
│  • Sets needs_clarification if ambiguous                    │
└─────────────┬───────────────────────────────────────────────┘
              │ requested_tool: ["file_create", "file_open"]
              ▼
┌─────────────────────────────────────────────────────────────┐
│  ClarificationService                                       │
│  • If needs_clarification: ask user, await answer           │
│  • Enrich query with answer, then continue                  │
└─────────────┬───────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────┐
│  SQH  (Secondary Query Handler — sqh_service.py)            │
│                                                             │
│  Step 1: SkillEngine.match_skill(query, requested_tools)    │
│    └── if a skill matches → expand_to_tasks() → SKIP LLM    │
│                                                             │
│  Step 2: Otherwise → LLM plan generation                    │
│    └── produces Task[] with input_bindings, control, …      │
└─────────────┬───────────────────────────────────────────────┘
              │ tasks: [Task, Task, ...]
              ▼
┌─────────────────────────────────────────────────────────────┐
│  Orchestrator  (DAG scheduler)                              │
│  • Resolves dependencies                                    │
│  • Batches independent tasks for parallel execution         │
│  • Handles approvals via approval_coordinator               │
└─────────────┬───────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────┐
│  ExecutionEngine                                            │
│  • Server tasks → ServerToolExecutor → BaseTool.execute()   │
│  • Client tasks → emitted to Electron via socket            │
│  • Resolves input_bindings via JSONPath + flat-key fallback │
└─────────────┬───────────────────────────────────────────────┘
              │
              ▼
        ┌─────────────┐         ┌─────────────────┐
        │ ToolRegistry│  ←──    │ PluginManager   │
        │ (in-memory) │         │ scans plugins/  │
        └─────────────┘         │ at boot, fills  │
                                │ registry with   │
                                │ shipped tools   │
                                └─────────────────┘
              │
              ▼
        ┌─────────────────────────────┐
        │  Tool implementations        │
        │  • legacy: server/tools/...  │
        │  • plugin: installed/.../tools/ │
        └─────────────────────────────┘
              │
              ▼
        Kernel events → ActivityLog (FTS5 SQLite)
        Tool outputs → orchestrator → next tasks → final TTS summary
```

**Who calls whom**

| Caller | Callee | Interface |
|---|---|---|
| `PluginManager` | `ToolRegistry` | adds `ToolMetadata` for plugin-shipped tools |
| `PluginManager` | `ToolInstanceRegistry` | registers `BaseTool` instances |
| `PluginManager` | `SkillEngine` | registers skill YAMLs found in the plugin dir |
| `SQH` | `SkillEngine.match_skill()` | short-circuit LLM if a recipe matches |
| `SQH` | `SkillEngine.expand_to_tasks()` | produce `Task[]` from a skill |
| `Orchestrator` | `BindingResolver` | turn `$.step_1.data.x` into a value |
| `ExecutionEngine` | `ToolInstanceRegistry.get()` | look up live tool instance |
| `BaseTool.execute()` | tool's `_execute()` | actual work |
| Tool | `KernelEventBus` | emit completion event → ActivityLog logs it |

---

## 3. Layout of a plugin

```
server/plugins/installed/<your_plugin>/
├── plugin.json                ← required manifest
├── tools/                     ← optional — Python files, each with one or more BaseTool classes
│   ├── __init__.py            (empty)
│   ├── my_tool.py
│   └── another_tool.py
└── skills/                    ← optional — YAML skill DAGs
    └── my_recipe.yaml
```

### plugin.json fields

```json
{
  "name": "vision",                       // required, unique
  "version": "1.0.0",
  "display_name": "Vision",
  "description": "Camera, screen analysis, OCR.",
  "author": "your-name",
  "capabilities": ["camera", "ocr", "screen_analysis"],
  "tools": ["camera_capture", "ocr_image"],   // optional: claim names that exist somewhere
  "skills": [
    {"name": "describe_screen", "file": "skills/describe_screen.yaml"}
  ],
  "dependencies": [],                     // names of other plugins required first
  "config_schema": {
    "ocr_engine": {"type": "string", "default": "tesseract"}
  },
  "enabled": true
}
```

The `tools` array is **for documentation and ownership tracking**. Tools shipped inside `tools/` are auto-discovered regardless of whether they're listed there — listing them just makes the manifest more informative. The `PluginManager` will warn if any name in `tools` doesn't resolve to a real tool anywhere in the registry.

---

## 4. Writing a tool inside a plugin (recommended for new code)

Drop a `.py` file into `installed/<plugin>/tools/`. The class extends `BaseTool` and declares its metadata as **class attributes**:

```python
# server/plugins/installed/vision/tools/screen_describe.py
from app.plugins.tools.tool_base import BaseTool, ToolOutput


class ScreenDescribeTool(BaseTool):
    TOOL_DESCRIPTION = "Capture the screen and describe what's on it."
    EXECUTION_TARGET = "server"          # "server" or "client"
    PARAMS_SCHEMA = {
        "monitor": {"type": "integer", "required": False, "default": 0,
                    "description": "Monitor index (0 = primary)."},
        "include_text": {"type": "boolean", "default": True,
                         "description": "Run OCR and include detected text."},
    }
    OUTPUT_SCHEMA = {
        "data": {
            "description": {"type": "string"},
            "ocr_text": {"type": "string"},
            "screenshot_path": {"type": "string"},
        }
    }
    EXAMPLES = [
        {"user_utterance": "what's on my screen"},
        {"user_utterance": "describe what you see"},
    ]
    SEMANTIC_TAGS = ["vision", "screen", "describe"]

    def get_tool_name(self) -> str:
        return "screen_describe"

    async def _execute(self, inputs):
        monitor = self.get_input(inputs, "monitor", 0)
        include_text = self.get_input(inputs, "include_text", True)

        # ... do work ...

        return ToolOutput(success=True, data={
            "description": "A code editor with main.py open.",
            "ocr_text": "..." if include_text else "",
            "screenshot_path": "/tmp/screen.png",
        })
```

That's it. **No JSON registry edits, no manual registration.** At boot, `PluginManager._discover_plugin_tools` will:

1. Find this `.py` file under `installed/vision/tools/`
2. Import it
3. See `ScreenDescribeTool extends BaseTool`
4. Read class attributes to build a full `ToolMetadata`
5. Instantiate it and call `set_schemas(...)`
6. Register the metadata in `ToolRegistry` and the instance in `ToolInstanceRegistry`

After that, PQH/SQH/orchestrator/executor can use it like any other tool.

### Class-attribute reference

| Attribute | Type | Default | Purpose |
|---|---|---|---|
| `TOOL_DESCRIPTION` | str | first line of docstring | What the tool does, shown to the LLM |
| `EXECUTION_TARGET` | `"server"` or `"client"` | `"server"` | Where the tool runs |
| `PARAMS_SCHEMA` | dict | `{}` | Input validation schema |
| `OUTPUT_SCHEMA` | dict | `{}` | Output contract (warns when fields missing) |
| `EXAMPLES` | list of dicts | `[]` | Sample utterances for PQH/UX |
| `SEMANTIC_TAGS` | list of str | `[]` | Hints for tool selection |

---

## 5. Writing a skill

Skills are YAML files in `installed/<plugin>/skills/`. They short-circuit LLM planning when a query matches a trigger pattern AND every required tool exists.

```yaml
# server/plugins/installed/system/skills/create_and_open.yaml
name: create_and_open
description: "Create a file with content and open it"
plugin: system
required_tools:
  - file_create
  - file_open
trigger_patterns:
  - "create .*(file|note|document).* and open"
  - "make .*(file|note|document).* and open"
steps:
  - task_id: create
    tool: file_create
    execution_target: server
    inputs_from_user: [name, content, directory]
  - task_id: open
    tool: file_open
    execution_target: client
    depends_on: [create]
    input_bindings:
      path: "$.create.data.file_path"
```

Reference it from `plugin.json`:
```json
"skills": [
  {"name": "create_and_open", "file": "skills/create_and_open.yaml"}
]
```

`SkillEngine.match_skill(query, available_tools)` walks all registered skills and returns the first one whose trigger regex matches AND whose `required_tools` are all present. `expand_to_tasks(skill, user_inputs)` returns a `Task[]` ready for the orchestrator.

---

## 6. Testing tools manually

Two ways: REPL helpers, or CLI subcommands.

### REPL / script

```python
from scripts.tool_tester import list_tools, describe_tool, test_tool, tools

# Show every tool, grouped by category
list_tools()

# Filter to one plugin
list_tools(category="system")

# Inspect one tool's schema
describe_tool("app_open")

# Run a tool by name
result = await test_tool("app_open", target="chrome")

# Run via attribute proxy — IDE autocompletes after stub generation
result = await tools.app_open(target="chrome")
```

The `tools` proxy uses `__dir__` to expose every registered tool name, so `dir(tools)` and most REPLs give you tab completion at runtime.

### IDE autocomplete (hover, ctrl-space on `tools.`)

Run once after adding/renaming/removing tools:

```bash
# Full helper (requires app environment)
python -m scripts.tool_tester --gen-stubs

# No-env fallback (reads tool_registry.json directly)
python server/scripts/_bootstrap_stubs.py
```

This writes `server/scripts/tools.pyi`. Type checkers (Pylance, Pyright, mypy) pick up the stub automatically. Hovering over `tools.app_open` will show the description and every parameter with its declared type.

### CLI

```bash
python -m scripts.tool_tester list
python -m scripts.tool_tester list --category system
python -m scripts.tool_tester describe app_open
python -m scripts.tool_tester run app_open --inputs '{"target":"chrome"}'
```

---

## 7. Adding a new plugin from scratch (vision example)

### 1. Create the directory
```
server/plugins/installed/vision/
├── plugin.json
├── tools/
│   └── screen_describe.py
└── skills/        # optional
```

### 2. Write `plugin.json`
```json
{
  "name": "vision",
  "version": "1.0.0",
  "display_name": "Vision",
  "description": "Camera, screen analysis, OCR.",
  "capabilities": ["camera", "ocr", "screen_analysis"],
  "tools": ["screen_describe"],
  "skills": [],
  "dependencies": [],
  "config_schema": {
    "ocr_engine": {"type": "string", "default": "tesseract"}
  },
  "enabled": true
}
```

### 3. Drop tools into `tools/`
See the `BaseTool` example above. **No further wiring needed.**

### 4. Restart the server
The `PluginManager.discover_and_load()` call inside `app/main.py` lifespan picks it up. Logs will show:

```
Loaded plugin vision v1.0.0 — claimed=1, shipped=1, skills=0
  ↳ shipped tool: screen_describe (from vision/screen_describe.py)
```

### 5. Regenerate stubs
```bash
python -m scripts.tool_tester --gen-stubs
```
Now `tools.screen_describe(...)` autocompletes in your IDE.

### 6. Verify in-app
The `plugin_info` tool (shipped by the system plugin) returns the full plugin list — useful both for debugging and as a capability the assistant can answer with:

```python
await tools.plugin_info()
# → {"plugins": [..., {"name": "vision", "tool_count": 1, "capabilities": [...] }, ...]}
```

---

## 8. Hearing plugin (sketch)

```
installed/hearing/
├── plugin.json                       # capabilities: ["mic", "vad", "transcribe"]
├── tools/
│   ├── audio_listen.py               # tool: capture_audio, target=server
│   ├── audio_transcribe.py           # tool: transcribe, target=server
│   └── voice_print.py                # tool: voice_match, target=server
└── skills/
    └── listen_and_transcribe.yaml    # capture_audio → transcribe
```

A skill could chain `capture_audio → transcribe` so "listen for 10 seconds and tell me what was said" triggers a single skill match instead of an LLM plan call.

---

## 9. Migration recipe for existing tools

Existing tools live in `server/tools/tools/<category>/` and are listed in `tool_registry.json`. **Do not bulk-move them.** When you do migrate one, follow this recipe per tool:

### 9.1 Move the file
```
server/tools/tools/system/my_tool.py
        ↓
server/plugins/installed/system/tools/my_tool.py
```

### 9.2 Fix relative imports
Each tool file uses `from ..base import BaseTool, ToolOutput`. After moving:
```python
# before
from ..base import BaseTool, ToolOutput
# after
from app.plugins.tools.tool_base import BaseTool, ToolOutput
```

### 9.3 Add class attributes (replaces JSON entry)
Read the tool's existing entry in `tool_registry.json` (`description`, `params_schema`, `output_schema`, `examples`, `semantic_tags`, `execution_target`). Pin them as class attributes on the tool class. Now the tool is fully self-describing.

### 9.4 Remove the entry from `tool_registry.json`
Delete the tool's block from its category in the registry. Re-run `python server/scripts/_bootstrap_stubs.py` to refresh stubs.

### 9.5 Restart and verify
- Server boot log shows `↳ shipped tool: my_tool`
- `python -m scripts.tool_tester describe my_tool` shows the metadata
- `python -m scripts.tool_tester run my_tool --inputs '{...}'` executes it

### 9.6 Conflict policy
If the same tool name appears in both the JSON registry AND a plugin dir, the JSON entry wins and the plugin one is ignored with a warning. So you can stage migrations safely: ship the new plugin tool, verify it loads, **then** remove the JSON entry.

---

## 10. Where things live

| Concern | Location |
|---|---|
| Plugin manifests | `server/plugins/installed/<name>/plugin.json` |
| Plugin-shipped tools | `server/plugins/installed/<name>/tools/*.py` |
| Skill DAGs | `server/plugins/installed/<name>/skills/*.yaml` |
| Plugin loader | `server/plugins/manager.py` |
| Plugin/skill models | `server/plugins/models.py` |
| Skill engine | `server/plugins/skills/skill_engine.py` |
| Legacy tools | `server/tools/tools/<category>/*.py` |
| Central tool registry | `server/tools/registry/tool_registry.json` |
| In-memory tool registry | `app.plugins.tools.registry_loader.ToolRegistry` |
| Live tool instances | `app.plugins.tools.tool_base.ToolInstanceRegistry` |
| Dev test helper | `server/scripts/tool_tester.py` |
| Generated IDE stubs | `server/scripts/tools.pyi` |

---

## 11. Common questions

**Q: Will adding a plugin slow down boot?**
The discovery scan is ~O(plugins × files). Each file is imported once. For ~10 plugins with a handful of tools each, total cost is well under a second.

**Q: Can a plugin override a built-in tool?**
No. If a tool name already exists, the plugin-shipped version is logged-and-skipped. Pick a different name (or remove the registry entry first when migrating).

**Q: Can plugins depend on each other?**
Yes — list the parent's name in `dependencies`. Manifests are loaded in alphabetical directory order, so if your plugin depends on `system`, it must come after it alphabetically OR list it in `dependencies` so the manager skips it cleanly when out of order.

**Q: How do skills find their required tools?**
`SkillEngine.match_skill()` is called with the list of tools PQH already chose. If those names cover the skill's `required_tools`, the skill matches. So skills *complement* PQH's tool selection — they don't replace it.

**Q: How do I disable a plugin without deleting files?**
Set `"enabled": false` in `plugin.json`. The manager records it as `disabled` and skips loading.

**Q: How do I hot-reload during development?**
```python
from plugins import get_plugin_manager
await get_plugin_manager().reload_plugin("vision")
```
This drops registered skills owned by the plugin and re-runs `_load_one`. Tool instances are not unregistered today (singleton registry), so renaming a tool requires a server restart.
