# SparkAI Server Enhancement Plan

> **Date**: 2026-05-19
> **Scope**: `server/` — FastAPI backend only (Electron UI wiring is out of scope for now)
> **Goal**: Make the server handle any single voice command end-to-end — from "create a file and open it" to "book me a cab and remind me at 6pm"

---

## Table of Contents

1. [Current Architecture Summary](#1-current-architecture-summary)
2. [Phase 0 — Fix Tool Output Chaining (Critical Bug)](#2-phase-0--fix-tool-output-chaining-critical-bug)
3. [Phase 1 — Shell Executor + System Command Power](#3-phase-1--shell-executor--system-command-power)
4. [Phase 2 — Plugin Architecture](#4-phase-2--plugin-architecture)
5. [Phase 3 — Task Scheduler + Reminders](#5-phase-3--task-scheduler--reminders)
6. [Phase 4 — Central Activity Log (Unified Trace)](#6-phase-4--central-activity-log-unified-trace)
7. [Phase 5 — External Action Bridge](#7-phase-5--external-action-bridge)
8. [Phase 6 — Response Speed Optimizations](#8-phase-6--response-speed-optimizations)
9. [Phase 7 — Artifact Store Hardening](#9-phase-7--artifact-store-hardening)
10. [Phase 8 — Scalability (Future-Proofing)](#10-phase-8--scalability-future-proofing)
11. [File Tree of New/Modified Files](#11-file-tree-of-newmodified-files)
12. [Dependency Order](#12-dependency-order)
13. [Design Decisions — Why NOT Redis for Task Queue](#13-design-decisions--why-not-redis-for-task-queue)

---

## 1. Current Architecture Summary

### What Already Works Well

```
Voice Command
    ↓
PQH (Tool Decision Engine — picks tools)
    ↓
SQH (Execution Plan Generator — produces Task[] JSON with bindings)
    ↓
Orchestrator (DAG scheduler — dependency resolution, parallel batching)
    ↓
ExecutionEngine (unified loop — server + client tool execution)
    ↓
ToolRegistry → ToolInstanceLoader → BaseTool.execute()
    ↓
KernelEventBus → PersistenceRouter (batch flush on desktop, write-through on prod)
```

**Strengths:**
- Clean kernel with event bus, persistence, and observability
- JSONPath-based `BindingResolver` for inter-task data flow
- LLM provider fallback chain (Groq → Gemini → OpenRouter)
- Streaming TTS with concurrent chunk dispatch
- Artifact store with search-by-keyword
- Background learning (fact extraction, profile summaries)
- Tool registry loaded from JSON manifest with schema validation

### What's Missing or Broken

| Gap | Impact |
|-----|--------|
| Tool outputs don't consistently expose fields that downstream tools expect | "Create file then open it" fails |
| No plugin system — tools are flat, no installable bundles | Can't add vision/hearing/shopping as modules |
| No scheduler — can't do "remind me at 6pm" or "run this daily" | Missing core assistant capability |
| No shell executor — AI can't run commands like Claude Code does | Severely limits system-level tasks |
| No unified activity log — events are per-tool, not session-level | AI can't answer "what did we do about X?" |
| No external action framework — only Gmail OAuth scaffold exists | Can't book, shop, or interact with services |
| Artifact records lack content hashing | Duplicate detection impossible |
| No tool result caching | Repeated queries re-execute tools |

---

## 2. Phase 0 — Fix Tool Output Chaining (Critical Bug)

### Problem

When the LLM generates a plan like:
```json
{
  "tasks": [
    {"task_id": "step_1", "tool": "file_create", "inputs": {"name": "notes.txt", "content": "hello"}},
    {"task_id": "step_2", "tool": "file_open", "depends_on": ["step_1"],
     "input_bindings": {"path": "$.step_1.data.file_path"}}
  ]
}
```

Step 2 fails because:
1. `file_create` tool's `execute()` returns `ToolOutput(data={"message": "File created"})` — it doesn't include `file_path` in the output data.
2. The `BindingResolver` looks for `$.step_1.data.file_path` → finds nothing → binding returns `None` → downstream tool gets no path → ENOENT.

### Root Cause

Tools were written before the binding system existed. They return human-friendly messages but not machine-readable output fields that other tools can consume.

### Fix — 3 Parts

#### Part A: Define a Tool Output Contract

Every tool's `execute()` must return all fields declared in its `output_schema` (from `tool_registry.json`). This is the contract that `input_bindings` depend on.

**File**: `server/tools/tools/base.py`

Add a post-execution validator in `BaseTool`:
```python
async def execute(self, inputs: dict) -> ToolOutput:
    output = await self._run(inputs)
    self._validate_output_contract(output)
    return output

def _validate_output_contract(self, output: ToolOutput) -> None:
    """Warn if declared output_schema fields are missing from output.data."""
    if not output.success or not self.output_schema:
        return
    declared = set(self.output_schema.get("properties", {}).keys())
    actual = set(output.data.keys())
    missing = declared - actual
    if missing:
        logger.warning(
            "Tool '%s' output missing declared fields: %s (has: %s)",
            self.tool_name, missing, actual,
        )
```

#### Part B: Audit and Fix Every Tool's Output

Go through each tool in `server/tools/tools/` and ensure `output.data` includes all fields from its `output_schema`.

**Priority tools to fix** (these are in the most common chains):

| Tool | Must return in `output.data` |
|------|------------------------------|
| `file_create` | `file_path`, `file_name`, `directory` |
| `folder_create` | `folder_path`, `folder_name` |
| `app_open` | `app_name`, `pid`, `window_title` |
| `screenshot` | `file_path`, `artifact_id` |
| `web_search` | `results` (list), `query` |
| `web_scrape` | `content`, `url`, `title` |
| `artifact_resolve` | `file_path`, `artifact_id`, `preferred_app` |
| `shell_agent` | `stdout`, `stderr`, `exit_code`, `working_dir` |

**Example fix for `file_create`** (in its `_run` method):
```python
# BEFORE
return ToolOutput(success=True, data={"message": f"Created {file_name}"})

# AFTER
return ToolOutput(success=True, data={
    "file_path": str(full_path),
    "file_name": file_name,
    "directory": str(full_path.parent),
    "message": f"Created {file_name}",
})
```

#### Part C: Improve SQH Prompt for Better Binding Generation

The LLM sometimes forgets to generate `input_bindings`. Strengthen the SQH prompt.

**File**: `server/app/prompts/sqh_prompt.py`

Add to the system prompt after the TASK OBJECT SCHEMA section:
```
━━━ INPUT BINDING RULES (CRITICAL) ━━━
When task B depends on output from task A:
1. Add A's task_id to B's "depends_on" array.
2. Add a binding in B's "input_bindings": {"param": "$.A_task_id.data.field"}.
3. Do NOT hardcode paths or values that come from a previous task's output.
4. Common binding patterns:
   - file_create → file_open: {"path": "$.step_1.data.file_path"}
   - folder_create → file_create: {"directory": "$.step_1.data.folder_path"}
   - artifact_resolve → file_open: {"path": "$.step_1.data.file_path"}
   - web_search → summarize: {"text": "$.step_1.data.results"}
```

#### Part D: Add Binding Fallback in ExecutionEngine

When a binding resolves to `None`, check `ToolContextService._recent_outputs` for the dependency task's output and try to extract the field from there.

**File**: `server/app/kernel/execution/binding_resolver.py`

In `_resolve_single_binding`, after the JSONPath match fails:
```python
if not matches:
    # Fallback: try flat key lookup in output.data
    flat_key = parts[-1] if len(parts) > 2 else None
    if flat_key and isinstance(source_task.output.data, dict):
        fallback_value = source_task.output.data.get(flat_key)
        if fallback_value is not None:
            logger.info("Binding fallback: found '%s' via flat key in %s", flat_key, task_id)
            return fallback_value
    raise ValueError(f"JSONPath matched nothing: {jsonpath_expr}")
```

### Verification

After this phase, the following voice command must work end-to-end:
```
"Create a text file called my_notes with 'hello world' in it, then open it"
```

Expected: `file_create` runs → returns `file_path` in data → `file_open` picks it up via binding → file opens.

---

## 3. Phase 1 — Shell Executor + System Command Power

### Goal

Give SparkAI the ability to run shell commands on the host system, similar to how Claude Code operates. This is the single biggest capability unlock.

### Architecture

```
server/app/services/shell/
├── __init__.py
├── executor.py          # ShellExecutor — subprocess runner
├── sandbox.py           # SecuritySandbox — whitelist/blocklist enforcement
└── session_manager.py   # ShellSessionManager — working dir + env tracking
```

### Step 1: SecuritySandbox

```python
# server/app/services/shell/sandbox.py

class SecuritySandbox:
    """Enforces command safety before execution."""

    ALLOWED_PREFIXES = {
        "git", "npm", "npx", "pip", "python", "node",
        "dir", "ls", "cat", "type", "echo", "mkdir", "cd",
        "code", "start", "explorer", "notepad",
        "curl", "wget", "tar", "unzip",
        "docker", "docker-compose",
    }

    BLOCKED_PATTERNS = [
        r"rm\s+(-rf|--force)\s+[/\\]",    # rm -rf /
        r"del\s+/s\s+/q",                   # del /s /q
        r"format\s+[a-z]:",                  # format C:
        r"reg\s+(delete|add)",               # registry edits
        r"net\s+user",                       # user management
        r"shutdown|restart",                  # system shutdown
        r"taskkill\s+/f\s+/im\s+\*",        # kill all processes
    ]

    def validate(self, command: str) -> tuple[bool, str]:
        """Returns (allowed, reason)."""
        # Check blocked patterns first
        for pattern in self.BLOCKED_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return False, f"Blocked by security pattern: {pattern}"

        # Check if first token is in allowed prefixes
        first_token = command.strip().split()[0].lower()
        if first_token in self.ALLOWED_PREFIXES:
            return True, "Whitelisted command"

        # Unknown command — requires approval
        return False, "requires_approval"
```

### Step 2: ShellExecutor

```python
# server/app/services/shell/executor.py

class ShellExecutor:
    """Runs shell commands with timeout, output capture, and security."""

    def __init__(self):
        self.sandbox = SecuritySandbox()
        self.session_manager = ShellSessionManager()

    async def execute(
        self,
        command: str,
        *,
        user_id: str,
        working_dir: str | None = None,
        timeout_s: float = 30.0,
        allow_network: bool = False,
        env_overrides: dict[str, str] | None = None,
    ) -> ShellResult:
        # 1. Security check
        allowed, reason = self.sandbox.validate(command)
        if not allowed and reason != "requires_approval":
            return ShellResult(success=False, exit_code=-1, error=reason)
        if reason == "requires_approval":
            # Hook into approval_coordinator — task will be paused
            return ShellResult(success=False, exit_code=-1, error="approval_required",
                             needs_approval=True, approval_question=f"Allow: {command}?")

        # 2. Resolve working directory
        cwd = self.session_manager.get_cwd(user_id, working_dir)

        # 3. Build environment
        env = self.session_manager.build_env(user_id, env_overrides, allow_network)

        # 4. Execute
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd),
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_s
            )
            return ShellResult(
                success=(proc.returncode == 0),
                exit_code=proc.returncode or 0,
                stdout=stdout.decode("utf-8", errors="replace")[:10000],
                stderr=stderr.decode("utf-8", errors="replace")[:5000],
                working_dir=str(cwd),
            )
        except asyncio.TimeoutError:
            proc.kill()
            return ShellResult(success=False, exit_code=-1, error=f"Timed out after {timeout_s}s")
```

### Step 3: ShellSessionManager

Tracks per-user working directory and environment across commands within a session.

```python
# server/app/services/shell/session_manager.py

class ShellSessionManager:
    """Maintains per-user shell session state (cwd, env vars)."""

    def __init__(self):
        self._sessions: dict[str, ShellSession] = {}

    def get_cwd(self, user_id: str, override: str | None = None) -> Path:
        session = self._sessions.get(user_id)
        if override:
            path = Path(override).expanduser().resolve()
            if path.is_dir():
                self._ensure_session(user_id).cwd = path
                return path
        if session and session.cwd.is_dir():
            return session.cwd
        return Path.home()

    def update_cwd(self, user_id: str, new_cwd: str) -> None:
        """Called after a cd command succeeds."""
        path = Path(new_cwd).expanduser().resolve()
        if path.is_dir():
            self._ensure_session(user_id).cwd = path
```

### Step 4: Register as Tools

Register two new tools in the tool registry:

**`shell_execute`** — runs a single command:
```json
{
  "tool_name": "shell_execute",
  "description": "Execute a shell command on the host system",
  "execution_target": "server",
  "params_schema": {
    "command": {"type": "string", "required": true},
    "working_dir": {"type": "string"},
    "timeout_s": {"type": "number", "default": 30},
    "allow_network": {"type": "boolean", "default": false}
  },
  "output_schema": {
    "stdout": {"type": "string"},
    "stderr": {"type": "string"},
    "exit_code": {"type": "integer"},
    "working_dir": {"type": "string"}
  }
}
```

**`system_query`** — read-only system info (already exists, ensure it exposes enough):
- OS version, CPU/RAM usage, disk space, running processes, network interfaces

### Step 5: Wire Approval Gate

For commands that aren't whitelisted, the tool should set `control.requires_approval = true` in the task. The existing `approval_coordinator.py` and the `_handle_approval_gate` in `ExecutionEngine` handle the rest.

Concretely, the `shell_execute` tool's `_run()` method checks the sandbox. If `needs_approval`, it returns:
```python
return ToolOutput(
    success=False,
    data={"needs_approval": True, "command": command},
    error="Command requires user approval",
)
```

Then the execution engine sees the failure, checks `ToolContextService.suggest_retry_strategy()`, and the SQH can re-plan with `control.requires_approval = true`.

**Better approach**: Add a pre-execution hook in `ExecutionEngine._execute_single_server_task()`:

```python
# Before executing the tool, check if it needs dynamic approval
if task.tool == "shell_execute":
    allowed, reason = get_shell_executor().sandbox.validate(
        resolved_inputs.get("command", "")
    )
    if reason == "requires_approval" and not (task.control and task.control.requires_approval):
        # Inject approval gate dynamically
        task.task.control = TaskControl(
            requires_approval=True,
            approval_question=f"Allow command: {resolved_inputs.get('command', '')}?",
        )
```

---

## 4. Phase 2 — Plugin Architecture

### Goal

Organize tools into installable plugin bundles. Each plugin = one "organ" of the assistant (vision, hearing, web, system, messaging, etc.).

### Directory Structure

```
server/plugins/
├── __init__.py
├── manager.py              # PluginManager — discovery, loading, lifecycle
├── models.py               # PluginManifest, PluginState, SkillDefinition
├── installed/              # Each subdirectory is a plugin
│   ├── system/
│   │   ├── plugin.json     # Manifest
│   │   ├── tools/          # Tool implementations
│   │   └── skills/         # Multi-tool skill definitions (YAML)
│   ├── web/
│   │   ├── plugin.json
│   │   ├── tools/
│   │   └── skills/
│   ├── messaging/
│   │   ├── plugin.json
│   │   ├── tools/
│   │   └── skills/
│   ├── media/
│   │   └── ...
│   └── ai/
│       └── ...
└── skills/
    ├── __init__.py
    └── skill_engine.py     # SkillEngine — executes multi-tool skill DAGs
```

### Step 1: Plugin Manifest Format

Each plugin has a `plugin.json`:

```json
{
  "name": "system",
  "version": "1.0.0",
  "display_name": "System Control",
  "description": "OS-level operations — files, apps, shell, clipboard, screen",
  "author": "spark-core",
  "capabilities": ["file_system", "app_control", "shell", "clipboard", "screen"],
  "tools": [
    "app_open", "file_create", "folder_create", "shell_execute",
    "screenshot", "clipboard", "brightness", "sound", "battery",
    "system_info", "notification"
  ],
  "skills": [
    {"name": "create_and_open", "file": "skills/create_and_open.yaml"},
    {"name": "organize_folder", "file": "skills/organize_folder.yaml"}
  ],
  "dependencies": [],
  "config_schema": {
    "shell_timeout_default": {"type": "number", "default": 30},
    "require_approval_for_shell": {"type": "boolean", "default": true}
  },
  "enabled": true
}
```

### Step 2: PluginManager

```python
# server/plugins/manager.py

class PluginManager:
    """Discovers, loads, and manages plugin lifecycle."""

    def __init__(self, plugins_dir: Path):
        self.plugins_dir = plugins_dir
        self.plugins: dict[str, PluginState] = {}
        self.skill_engine = SkillEngine()

    async def discover_and_load(self) -> None:
        """Scan plugins/installed/ for plugin.json files and load them."""
        for plugin_dir in self.plugins_dir.iterdir():
            if not plugin_dir.is_dir():
                continue
            manifest_path = plugin_dir / "plugin.json"
            if not manifest_path.exists():
                continue
            manifest = PluginManifest.from_file(manifest_path)
            if not manifest.enabled:
                continue

            # Check dependencies
            missing_deps = self._check_dependencies(manifest)
            if missing_deps:
                logger.warning("Plugin '%s' has unmet dependencies: %s", manifest.name, missing_deps)
                continue

            # Register tools from this plugin
            self._register_plugin_tools(manifest, plugin_dir)

            # Register skills from this plugin
            self._register_plugin_skills(manifest, plugin_dir)

            self.plugins[manifest.name] = PluginState(
                manifest=manifest,
                status="loaded",
                tool_count=len(manifest.tools),
            )
            logger.info("Loaded plugin: %s (%d tools)", manifest.name, len(manifest.tools))

    def _register_plugin_tools(self, manifest: PluginManifest, plugin_dir: Path) -> None:
        """Register each tool from the plugin into the global ToolRegistry."""
        # Tools are already in server/tools/tools/<category>/
        # The plugin manifest just declares which tools belong to it.
        # Future: tools could live inside the plugin directory itself.
        pass

    def _register_plugin_skills(self, manifest: PluginManifest, plugin_dir: Path) -> None:
        """Load skill YAML definitions and register them."""
        for skill_def in manifest.skills:
            skill_path = plugin_dir / skill_def["file"]
            if skill_path.exists():
                self.skill_engine.register_skill(skill_path)

    def get_plugin(self, name: str) -> PluginState | None:
        return self.plugins.get(name)

    def list_plugins(self) -> list[dict]:
        return [p.to_dict() for p in self.plugins.values()]

    async def reload_plugin(self, name: str) -> bool:
        """Hot-reload a single plugin (for development)."""
        ...
```

### Step 3: Skill Engine

A "skill" is a pre-defined multi-tool workflow. Instead of the LLM re-inventing "create file then open it" every time, a skill defines the DAG once.

```yaml
# server/plugins/installed/system/skills/create_and_open.yaml
name: create_and_open
description: "Create a file with content and open it"
trigger_patterns:
  - "create .* and open"
  - "make .* file .* open"
steps:
  - task_id: create
    tool: file_create
    inputs_from_user: [name, content, directory]
  - task_id: open
    tool: file_open
    depends_on: [create]
    input_bindings:
      path: "$.create.data.file_path"
```

```python
# server/plugins/skills/skill_engine.py

class SkillEngine:
    """Loads and expands skill definitions into Task[] for the orchestrator."""

    def __init__(self):
        self.skills: dict[str, SkillDefinition] = {}

    def register_skill(self, yaml_path: Path) -> None:
        skill = SkillDefinition.from_yaml(yaml_path)
        self.skills[skill.name] = skill

    def match_skill(self, query: str, tool_names: list[str]) -> SkillDefinition | None:
        """Check if a query matches a known skill pattern."""
        for skill in self.skills.values():
            if skill.matches(query, tool_names):
                return skill
        return None

    def expand_to_tasks(
        self, skill: SkillDefinition, user_inputs: dict
    ) -> list[Task]:
        """Convert a skill definition into concrete Task objects."""
        tasks = []
        for step in skill.steps:
            inputs = {}
            for key in step.get("inputs_from_user", []):
                if key in user_inputs:
                    inputs[key] = user_inputs[key]
            tasks.append(Task(
                task_id=step["task_id"],
                tool=step["tool"],
                execution_target=step.get("execution_target", "server"),
                depends_on=step.get("depends_on", []),
                inputs=inputs,
                input_bindings=step.get("input_bindings", {}),
            ))
        return tasks
```

### Step 4: Integration with SQH

In `sqh_service.py`, before calling the LLM, check if a matching skill exists:

```python
# In process_sqh(), after getting pqh_response:
skill = get_plugin_manager().skill_engine.match_skill(
    pqh_response.cognitive_state.user_query,
    pqh_response.requested_tool or [],
)
if skill:
    tasks = skill_engine.expand_to_tasks(skill, user_inputs_from_pqh)
    # Skip LLM call entirely — use pre-defined task DAG
else:
    # Existing LLM-based plan generation
    ...
```

### Step 5: Migration

Move existing tools into plugin directories logically:

| Current Location | Plugin |
|------------------|--------|
| `tools/tools/system/` | `plugins/installed/system/` |
| `tools/tools/web/` | `plugins/installed/web/` |
| `tools/tools/messaging/` | `plugins/installed/messaging/` |
| `tools/tools/media/` | `plugins/installed/media/` |
| `tools/tools/ai/` | `plugins/installed/ai/` |
| `tools/tools/file_system/` | `plugins/installed/system/` (merge) |
| `tools/tools/google/` | `plugins/installed/google/` |

**Note**: This is a gradual migration. The existing `ToolRegistry` + `tool_registry.json` continue to work. Plugins just declare which tools they own. Tools can still live in `server/tools/tools/` until they're physically moved.

---

## 5. Phase 3 — Task Scheduler + Reminders

### Goal

"Remind me to call Ram at 6pm", "Check my email every morning at 9am", "Run the backup script daily at midnight"

### Architecture

```
server/app/services/scheduler/
├── __init__.py
├── scheduler_service.py     # Core scheduler engine
├── models.py                # ScheduledTask, Reminder dataclasses
├── persistence.py           # SQLite-backed storage (local, no Redis)
└── trigger_handler.py       # What happens when a schedule fires
```

### Why SQLite (Not Redis)

- This is a **desktop-first** app. Redis is a separate service to manage.
- Scheduled tasks must **survive restarts**. In-memory won't work.
- SQLite is embedded, zero-config, and perfect for local persistence.
- The execution engine stays in-memory (it's ephemeral per-session). Only the *schedule definitions* need persistence.

### Step 1: Models

```python
# server/app/services/scheduler/models.py

@dataclass
class ScheduledTask:
    id: str                          # uuid
    user_id: str
    task_type: str                   # "reminder" | "recurring" | "one_shot"
    label: str                       # human-readable: "Call Ram"
    cron_expression: str | None      # "0 9 * * *" for recurring, None for one-shot
    trigger_at: datetime | None      # For one-shot/reminders
    task_plan: list[dict] | None     # Pre-built Task[] JSON (for recurring tool chains)
    notification_text: str | None    # For reminders — what to say/show
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.now)
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    run_count: int = 0
```

### Step 2: SQLite Persistence

```python
# server/app/services/scheduler/persistence.py

class SchedulerStore:
    """SQLite-backed storage for scheduled tasks."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_table()

    def _ensure_table(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_tasks (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    label TEXT NOT NULL,
                    cron_expression TEXT,
                    trigger_at TEXT,
                    task_plan TEXT,
                    notification_text TEXT,
                    enabled INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_run_at TEXT,
                    next_run_at TEXT,
                    run_count INTEGER DEFAULT 0
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_next_run ON scheduled_tasks(next_run_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_user ON scheduled_tasks(user_id)")

    def add(self, task: ScheduledTask) -> None: ...
    def get(self, task_id: str) -> ScheduledTask | None: ...
    def list_for_user(self, user_id: str) -> list[ScheduledTask]: ...
    def list_due(self, before: datetime) -> list[ScheduledTask]: ...
    def update_last_run(self, task_id: str, ran_at: datetime, next_at: datetime | None) -> None: ...
    def delete(self, task_id: str) -> bool: ...
```

### Step 3: Scheduler Service

```python
# server/app/services/scheduler/scheduler_service.py

class SchedulerService:
    """Background scheduler that checks for due tasks every 30 seconds."""

    def __init__(self):
        self.store = SchedulerStore(PathManager().get_db_dir() / "scheduler.db")
        self._running = False
        self._poll_task: asyncio.Task | None = None

    async def start(self) -> None:
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("Scheduler started (poll interval: 30s)")

    async def stop(self) -> None:
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()

    async def schedule_reminder(
        self, user_id: str, label: str, trigger_at: datetime, text: str
    ) -> ScheduledTask:
        task = ScheduledTask(
            id=uuid.uuid4().hex,
            user_id=user_id,
            task_type="reminder",
            label=label,
            trigger_at=trigger_at,
            next_run_at=trigger_at,
            notification_text=text,
        )
        self.store.add(task)
        return task

    async def schedule_recurring(
        self, user_id: str, label: str, cron_expr: str, task_plan: list[dict]
    ) -> ScheduledTask:
        next_run = croniter(cron_expr, datetime.now()).get_next(datetime)
        task = ScheduledTask(
            id=uuid.uuid4().hex,
            user_id=user_id,
            task_type="recurring",
            label=label,
            cron_expression=cron_expr,
            task_plan=task_plan,
            next_run_at=next_run,
        )
        self.store.add(task)
        return task

    async def _poll_loop(self) -> None:
        while self._running:
            await asyncio.sleep(30)
            due_tasks = self.store.list_due(before=datetime.now())
            for task in due_tasks:
                await self._trigger(task)

    async def _trigger(self, task: ScheduledTask) -> None:
        handler = get_trigger_handler()
        if task.task_type == "reminder":
            await handler.fire_reminder(task)
        elif task.task_type == "recurring":
            await handler.fire_recurring(task)

        # Update next run
        next_at = None
        if task.cron_expression:
            next_at = croniter(task.cron_expression, datetime.now()).get_next(datetime)
        self.store.update_last_run(task.id, datetime.now(), next_at)
```

### Step 4: Trigger Handler

```python
# server/app/services/scheduler/trigger_handler.py

class TriggerHandler:
    """Handles what happens when a scheduled task fires."""

    async def fire_reminder(self, task: ScheduledTask) -> None:
        """Send notification + optional TTS."""
        # 1. Desktop notification
        from app.agent.desktop_notifications import notify
        await notify(task.user_id, title="Reminder", body=task.notification_text or task.label)

        # 2. Socket event (Electron picks this up)
        from app.socket.utils import socket_emit
        await socket_emit("reminder:fired", {
            "task_id": task.id,
            "label": task.label,
            "text": task.notification_text,
        }, user_id=task.user_id)

        # 3. Emit kernel event for activity log
        await emit_kernel_event(KernelEvent(
            event_type="reminder_fired",
            user_id=task.user_id,
            task_id=task.id,
            payload={"label": task.label, "text": task.notification_text},
        ))

    async def fire_recurring(self, task: ScheduledTask) -> None:
        """Re-execute a stored task plan."""
        if not task.task_plan:
            return
        tasks = [Task(**t) for t in task.task_plan]
        orchestrator = get_orchestrator()
        engine = get_execution_engine()
        await orchestrator.cleanup_user_state(task.user_id)
        await orchestrator.register_tasks(task.user_id, tasks)
        await engine.start_execution(task.user_id)
```

### Step 5: Register Tools

Two new tools:

**`set_reminder`** (server):
```json
{
  "tool_name": "set_reminder",
  "description": "Set a reminder that will notify the user at a specific time",
  "params_schema": {
    "label": {"type": "string", "required": true},
    "trigger_at": {"type": "string", "description": "ISO datetime or natural language like '6pm today'"},
    "notification_text": {"type": "string"}
  },
  "output_schema": {
    "task_id": {"type": "string"},
    "trigger_at": {"type": "string"},
    "label": {"type": "string"}
  }
}
```

**`schedule_task`** (server):
```json
{
  "tool_name": "schedule_task",
  "description": "Schedule a recurring task with a cron expression",
  "params_schema": {
    "label": {"type": "string", "required": true},
    "cron_expression": {"type": "string", "required": true},
    "task_plan": {"type": "array", "description": "Pre-built task JSON array"}
  }
}
```

### Step 6: Natural Language Time Parsing

Add a utility to parse "6pm today", "tomorrow morning", "every Monday at 9am" into datetime/cron:

```python
# server/app/utils/time_parser.py
# Use dateparser library for one-shot times
# Use a simple mapping for cron patterns:
#   "every morning" → "0 9 * * *"
#   "every hour" → "0 * * * *"
#   "every Monday" → "0 9 * * 1"
```

### Step 7: Startup Integration

In `app/main.py` lifespan, start the scheduler:

```python
# In startup:
from app.services.scheduler import get_scheduler_service
scheduler = get_scheduler_service()
await scheduler.start()

# In shutdown:
await scheduler.stop()
```

---

## 6. Phase 4 — Central Activity Log (Unified Trace)

### Goal

One place where SparkAI records everything it has done — conversations, tool executions, reminders, scheduled tasks. So when the user asks "what did we do about the Finland trip?", the AI can search this log.

### Architecture

```
server/app/services/activity/
├── __init__.py
├── activity_log.py         # ActivityLog service
├── models.py               # ActivityEntry, SessionRecord
└── store.py                # SQLite storage
```

### Data Model

```python
# server/app/services/activity/models.py

@dataclass
class ActivityEntry:
    id: str                     # uuid
    user_id: str
    session_id: str             # groups entries within one conversation
    entry_type: str             # "conversation" | "tool_execution" | "reminder" | "scheduled_task" | "external_action"
    timestamp: str              # ISO datetime
    tool_name: str | None       # which tool ran
    query: str | None           # what the user said
    result_summary: str         # compact summary of what happened
    success: bool
    metadata: dict              # any extra data (artifact_id, file_path, etc.)
    tags: list[str]             # searchable tags extracted from content
```

### How Events Flow In

The `ActivityLog` subscribes to the `KernelEventBus`:

```python
class ActivityLog:
    def __init__(self):
        self.store = ActivityStore(PathManager().get_db_dir() / "activity.db")

    def subscribe_to_kernel(self) -> None:
        bus = get_kernel_event_bus()
        bus.subscribe(self._on_kernel_event)

    async def _on_kernel_event(self, event: KernelEvent) -> None:
        if event.event_type in ("task_completed", "task_failed"):
            await self.store.insert(ActivityEntry(
                id=uuid.uuid4().hex,
                user_id=event.user_id,
                session_id=event.session_id or "",
                entry_type="tool_execution",
                timestamp=event.timestamp,
                tool_name=event.tool_name,
                result_summary=self._summarize_event(event),
                success=(event.status == "completed"),
                metadata=event.payload,
                tags=self._extract_tags(event),
            ))
```

Additionally, the chat service writes conversation entries:

```python
# In stream_service.py, after persisting assistant response:
await get_activity_log().log_conversation(
    user_id=user_id,
    session_id=request_id,
    query=query,
    response=msg,
)
```

### Search API

```python
async def search(
    self, user_id: str, query: str, limit: int = 20
) -> list[ActivityEntry]:
    """Full-text search across activity entries."""
    # SQLite FTS5 for fast text search
    return self.store.search(user_id, query, limit)

async def get_session_history(
    self, user_id: str, session_id: str
) -> list[ActivityEntry]:
    """Get all entries for a specific session."""
    return self.store.get_by_session(user_id, session_id)

async def get_recent(
    self, user_id: str, limit: int = 50
) -> list[ActivityEntry]:
    """Get most recent activity entries."""
    return self.store.get_recent(user_id, limit)
```

### Integration with Memory System

Update `background_learning.py` to also read from the activity log:

```python
# In _learn_from_recent():
# In addition to chat messages, also pull recent tool executions
activity_log = get_activity_log()
recent_activities = await activity_log.get_recent(user_id, limit=10)
# Feed these into the fact extraction prompt alongside messages
```

### Integration with PQH/SQH

Add recent activity context to the PQH prompt so the AI knows what it recently did:

```python
# In pqh_prompt.py build_system_prompt():
# Add a section with recent activities (last 5 tool executions)
recent = await get_activity_log().get_recent(user_id, limit=5)
activity_context = "\n".join(
    f"- [{a.timestamp}] {a.tool_name}: {a.result_summary}"
    for a in recent
)
```

### Modification to KernelEvent

Add `session_id` to `KernelEvent` so events can be grouped:

```python
# server/app/kernel/contracts/models.py
@dataclass
class KernelEvent:
    # ... existing fields ...
    session_id: Optional[str] = None  # ADD THIS — links events to a conversation session
```

---

## 7. Phase 5 — External Action Bridge

### Goal

Enable SparkAI to interact with external services — booking, shopping, email, calendar — through a unified framework.

### Architecture

```
server/app/features/
├── external_service/       # Already exists — OAuth + token management
│   ├── providers.py        # Provider registry
│   ├── oauth_token_service.py
│   ├── token_manager.py
│   └── encryption.py
├── bridge/                 # NEW — unified external action framework
│   ├── __init__.py
│   ├── action_bridge.py    # ExternalActionBridge
│   ├── rate_limiter.py     # Per-service rate limiting
│   └── browser_agent.py    # Headless browser fallback (Playwright)
└── gmail/                  # Already exists — first connector
    └── _client.py
```

### Step 1: ExternalActionBridge

```python
# server/app/features/bridge/action_bridge.py

class ExternalActionBridge:
    """Unified interface for tools that interact with external services."""

    def __init__(self):
        self.rate_limiter = RateLimiter()
        self.token_manager = get_token_manager()

    async def execute_external(
        self,
        service: str,          # "gmail", "calendar", "amazon", etc.
        action: str,           # "send_email", "create_event", "search_product"
        params: dict,
        user_id: str,
        requires_confirmation: bool = True,
    ) -> ExternalActionResult:
        # 1. Rate limit check
        if not self.rate_limiter.allow(service, user_id):
            return ExternalActionResult(success=False, error="Rate limited")

        # 2. Token management (OAuth refresh if needed)
        token = await self.token_manager.get_valid_token(service, user_id)
        if not token:
            return ExternalActionResult(
                success=False,
                error="not_authenticated",
                auth_url=self._get_auth_url(service),
            )

        # 3. Confirmation for money/irreversible actions
        if requires_confirmation:
            # This will be handled by approval_coordinator
            pass

        # 4. Execute via service-specific connector
        connector = self._get_connector(service)
        result = await connector.execute(action, params, token)

        # 5. Audit log
        await emit_kernel_event(KernelEvent(
            event_type="external_action",
            user_id=user_id,
            tool_name=f"{service}:{action}",
            status="success" if result.success else "failed",
            payload={"service": service, "action": action},
        ))

        return result
```

### Step 2: Add Provider Connectors

Extend `server/app/features/external_service/providers.py` with new services:

```python
PROVIDERS = {
    "gmail": { ... },          # Already exists
    "google_calendar": {
        "display_name": "Google Calendar",
        "scopes": ["https://www.googleapis.com/auth/calendar"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        ...
    },
    "spotify": {
        "display_name": "Spotify",
        "scopes": ["user-read-playback-state", "user-modify-playback-state"],
        ...
    },
    # Future: slack, notion, todoist, etc.
}
```

### Step 3: Browser Agent (Fallback for No-API Services)

For services without APIs (Zomato, Amazon, etc.), use Playwright:

```python
# server/app/features/bridge/browser_agent.py

class BrowserAgent:
    """Headless browser automation for services without APIs."""

    async def execute(self, url: str, steps: list[dict]) -> BrowserResult:
        """
        Steps are high-level actions like:
        [
            {"action": "navigate", "url": "https://amazon.in"},
            {"action": "search", "query": "wireless earbuds"},
            {"action": "screenshot", "selector": ".results"},
        ]
        """
        # Requires Playwright. Install via: pip install playwright && playwright install chromium
        ...
```

**Note**: This is a later addition. Start with API-based connectors first.

### Step 4: Register External Tools

Each external service registers its tools via its plugin manifest:

```json
{
  "name": "google",
  "tools": ["gmail_send", "gmail_read", "calendar_create", "calendar_list"],
  "requires_oauth": ["gmail", "google_calendar"]
}
```

---

## 8. Phase 6 — Response Speed Optimizations

### 1. Tool Result Cache

**File**: `server/app/services/cache/tool_cache.py`

```python
class ToolResultCache:
    """Short-TTL cache for idempotent tool results."""

    def __init__(self, default_ttl: int = 60):
        self._cache: dict[str, tuple[float, ToolOutput]] = {}
        self.default_ttl = default_ttl
        # Tools that are safe to cache
        self.cacheable_tools = {
            "weather", "system_info", "battery", "network",
            "web_search", "artifact_list",
        }

    def get(self, tool_name: str, inputs_hash: str) -> ToolOutput | None:
        if tool_name not in self.cacheable_tools:
            return None
        key = f"{tool_name}:{inputs_hash}"
        entry = self._cache.get(key)
        if entry and (time.time() - entry[0]) < self.default_ttl:
            return entry[1]
        return None

    def put(self, tool_name: str, inputs_hash: str, output: ToolOutput) -> None:
        if tool_name not in self.cacheable_tools:
            return
        self._cache[f"{tool_name}:{inputs_hash}"] = (time.time(), output)
```

Wire into `ServerToolExecutor.execute()`:

```python
# Before executing:
cache = get_tool_result_cache()
inputs_hash = hashlib.md5(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
cached = cache.get(tool_name, inputs_hash)
if cached:
    logger.info("Cache hit for %s", tool_name)
    return cached

# After executing:
cache.put(tool_name, inputs_hash, output)
```

### 2. LLM Response Cache

For identical prompts (greetings, simple queries):

```python
# In LLMManager.chat(), before trying providers:
prompt_hash = hashlib.md5(json.dumps(messages).encode()).hexdigest()
cached = self._response_cache.get(prompt_hash)
if cached and (time.time() - cached[0]) < 120:  # 2 min TTL
    return cached[1], "cache"
```

### 3. Warm Context Pool

Pre-compute embedding context at WebSocket connection time:

```python
# In socket connect handler:
async def on_connect(sid, environ):
    user_id = extract_user_id(environ)
    # Pre-warm user context in background
    asyncio.create_task(pre_warm_user_context(user_id))
```

---

## 9. Phase 7 — Artifact Store Hardening

### 1. Content Hashing

Add SHA-256 hash to `ArtifactRecord`:

```python
# In ArtifactStore.register_file():
import hashlib

file_hash = hashlib.sha256(path.read_bytes()).hexdigest()

# Check for duplicate
existing = self._find_by_hash(file_hash)
if existing:
    logger.info("Duplicate artifact detected: %s", existing.artifact_id)
    return existing  # Return existing instead of creating duplicate

record = ArtifactRecord(
    ...
    content_hash=file_hash,  # NEW FIELD
)
```

### 2. Auto-Cleanup Policy

```python
# server/app/path/artifact_cleanup.py

async def cleanup_old_artifacts(
    max_age_days: int = 30,
    max_total_mb: int = 500,
) -> int:
    """Remove artifacts older than max_age_days or when total exceeds max_total_mb."""
    store = get_artifact_store()
    records = store.list_artifacts(limit=9999)

    # Sort oldest first
    records.sort(key=lambda r: r.created_at)

    total_bytes = sum(r.size_bytes for r in records)
    removed = 0

    for record in records:
        too_old = (datetime.now(timezone.utc) - parse_iso(record.created_at)).days > max_age_days
        too_large = total_bytes > max_total_mb * 1024 * 1024

        if too_old or too_large:
            path = store.resolve_artifact_path(record)
            if path.exists():
                path.unlink()
            store.delete_record(record.artifact_id)
            total_bytes -= record.size_bytes
            removed += 1

    return removed
```

### 3. Artifact Kind Auto-Directory

Already works via `PathManager.get_artifact_dir(kind, user_id)`. No changes needed.

---

## 10. Phase 8 — Scalability (Future-Proofing)

### Desktop (Current Priority) — Keep It Simple

For desktop mode, the current in-memory architecture is correct:
- `TaskOrchestrator.states` → in-memory dict (one user, one process)
- `KernelEventBus` → in-memory subscriber list
- `ToolContextService` → in-memory deques
- No Redis, no message queues, no separate workers

**DO NOT add Redis, Celery, or message queues for desktop mode.**

### Production (Later, When Needed)

When you need to serve multiple users:

1. **Replace in-memory state with Redis**:
   - `TaskOrchestrator.states` → Redis hash per user
   - `KernelEventBus` → Redis Pub/Sub or Redis Streams
   - `ToolResultCache` → Redis with TTL

2. **Extract execution workers**:
   - API server enqueues tasks → Redis Stream
   - Worker processes dequeue and execute
   - Results written back to Redis → API server picks up

3. **Add horizontal scaling**:
   - Multiple API servers behind nginx
   - Sticky sessions for WebSocket (or Redis adapter for socket.io)

**But this is months away. Don't build it now.**

---

## 11. File Tree of New/Modified Files

```
server/
├── app/
│   ├── kernel/
│   │   ├── contracts/
│   │   │   └── models.py                  # MODIFY — add session_id to KernelEvent
│   │   └── execution/
│   │       ├── binding_resolver.py         # MODIFY — add fallback flat-key lookup
│   │       └── execution_engine.py         # MODIFY — add dynamic approval for shell
│   │
│   ├── services/
│   │   ├── shell/                          # NEW — Phase 1
│   │   │   ├── __init__.py
│   │   │   ├── executor.py
│   │   │   ├── sandbox.py
│   │   │   └── session_manager.py
│   │   │
│   │   ├── scheduler/                      # NEW — Phase 3
│   │   │   ├── __init__.py
│   │   │   ├── scheduler_service.py
│   │   │   ├── models.py
│   │   │   ├── persistence.py
│   │   │   └── trigger_handler.py
│   │   │
│   │   ├── activity/                       # NEW — Phase 4
│   │   │   ├── __init__.py
│   │   │   ├── activity_log.py
│   │   │   ├── models.py
│   │   │   └── store.py
│   │   │
│   │   └── cache/
│   │       └── tool_cache.py              # NEW — Phase 6
│   │
│   ├── features/
│   │   └── bridge/                         # NEW — Phase 5
│   │       ├── __init__.py
│   │       ├── action_bridge.py
│   │       ├── rate_limiter.py
│   │       └── browser_agent.py
│   │
│   ├── prompts/
│   │   └── sqh_prompt.py                  # MODIFY — add binding rules
│   │
│   ├── path/
│   │   ├── artifacts.py                   # MODIFY — add content_hash, cleanup
│   │   └── artifact_cleanup.py            # NEW — Phase 7
│   │
│   ├── utils/
│   │   └── time_parser.py                 # NEW — Phase 3
│   │
│   └── main.py                            # MODIFY — start scheduler in lifespan
│
├── plugins/                                # NEW — Phase 2
│   ├── __init__.py
│   ├── manager.py
│   ├── models.py
│   ├── installed/
│   │   ├── system/
│   │   │   ├── plugin.json
│   │   │   └── skills/
│   │   │       └── create_and_open.yaml
│   │   ├── web/
│   │   │   └── plugin.json
│   │   ├── messaging/
│   │   │   └── plugin.json
│   │   ├── media/
│   │   │   └── plugin.json
│   │   ├── ai/
│   │   │   └── plugin.json
│   │   └── google/
│   │       └── plugin.json
│   └── skills/
│       ├── __init__.py
│       └── skill_engine.py
│
└── tools/
    └── tools/
        └── (various)                      # MODIFY — fix output.data contracts
```

---

## 12. Dependency Order

```
Phase 0: Tool Output Chaining Fix          ← DO FIRST (unblocks everything)
    │
    ├── Phase 1: Shell Executor            ← biggest capability unlock
    │
    ├── Phase 2: Plugin Architecture       ← structural foundation
    │       │
    │       ├── Phase 3: Scheduler         ← uses plugin system for tool registration
    │       │
    │       └── Phase 5: External Bridge   ← builds on plugins + OAuth scaffold
    │
    ├── Phase 4: Activity Log              ← subscribes to kernel events (independent)
    │
    ├── Phase 6: Speed Optimizations       ← independent, can do anytime
    │
    └── Phase 7: Artifact Hardening        ← independent, small scope

Phase 8: Scalability                       ← ONLY when needed
```

### Recommended Execution Order

| Order | Phase | Effort | Impact |
|-------|-------|--------|--------|
| 1 | Phase 0 — Fix Tool Chaining | 1 day | Critical — unblocks multi-tool commands |
| 2 | Phase 1 — Shell Executor | 2 days | Huge — gives system command power |
| 3 | Phase 4 — Activity Log | 1-2 days | High — enables "what did we do" queries |
| 4 | Phase 2 — Plugin Architecture | 2-3 days | Structural — foundation for future plugins |
| 5 | Phase 3 — Scheduler + Reminders | 2 days | High user-value — "remind me", "run daily" |
| 6 | Phase 6 — Speed Optimizations | 1 day | Easy wins — cache hits avoid re-execution |
| 7 | Phase 7 — Artifact Hardening | 0.5 day | Small scope — hashing + cleanup |
| 8 | Phase 5 — External Bridge | 3-5 days | Large — depends on plugins + OAuth per service |
| - | Phase 8 — Scalability | Future | Only when multi-user is needed |

---

## 13. Design Decisions — Why NOT Redis for Task Queue

### The Question

> "Do we really need Redis for the task queue?"

### The Answer: No.

**Your app is desktop-first.** The execution engine runs in the same process as the API server. Tasks are ephemeral — they exist for one voice command and then they're done.

Here's what uses what:

| Component | Storage | Reason |
|-----------|---------|--------|
| Execution state (orchestrator) | **In-memory dict** | Ephemeral. Resets per command. One user. |
| Tool result cache | **In-memory dict** | Short TTL, single process |
| Kernel events | **In-memory → batch flush to Mongo** | Already correct in `PersistenceRouter` |
| Scheduled tasks | **SQLite** | Must survive restarts. Embedded, zero-config. |
| Activity log | **SQLite (FTS5)** | Must survive restarts. Needs full-text search. |
| Chat messages | **Redis (Upstash) + Mongo** | Already works. Keep it. |
| User profiles/memory | **Local JSON files** | Already works via `memory/user_profile.py` |

**Redis stays for what it's already used for**: chat message caching and cloud sync. But the execution pipeline, scheduler, and activity log are all local-first with embedded storage.

### When Redis Would Make Sense

Only if you later need:
- Multiple server processes sharing task state
- Cross-machine execution (e.g., tasks running on a cloud worker)
- Pub/Sub for real-time sync between multiple clients

That's Phase 8 territory. Not now.

---

## Appendix: Voice Command Test Cases

After all phases are implemented, these should work end-to-end:

| Voice Command | Expected Flow |
|---|---|
| "Create a file called notes.txt with my schedule, then open it" | PQH → SQH → `file_create` → binding → `file_open` |
| "Remind me to call Ram at 6pm" | PQH → `set_reminder` → scheduler stores → fires at 6pm → notification |
| "Install express and create a new Node.js server" | PQH → SQH → `shell_execute` (npm init, npm install, write file) |
| "What did we do yesterday?" | PQH → activity log search → stream response |
| "Check my email" | PQH → `gmail_read` (via external bridge + OAuth) → stream response |
| "Take a screenshot and open it" | PQH → SQH → `screenshot` → binding → `file_open` |
| "Run the backup script every night at midnight" | PQH → `schedule_task` → cron in SQLite → fires nightly |
| "What's the weather?" (asked again 2 min later) | Tool cache hit → instant response |

---

*This document is the single source of truth for the server enhancement. Each phase is self-contained and can be implemented independently (following the dependency order). Electron UI wiring will be planned separately after the server handles all flows correctly.*
