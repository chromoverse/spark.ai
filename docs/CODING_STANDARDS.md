# CODING_STANDARDS.md — How We Write Spark Code (v2)

## 1. Python (brain, body)

- Python 3.11+, `from __future__ import annotations`, full type hints on public functions.
- `ruff format` + `ruff check`; `mypy --strict` on `brain/app/core`, `llm`, `tools`, `gateway`.
- Pydantic v2 models at every boundary: HTTP bodies, socket payloads, tool inputs/outputs, LLM JSON.
- Async all the way in the brain; blocking work → `asyncio.to_thread`. Never `time.sleep`.
- `logger = logging.getLogger(__name__)`, structured JSON logs with `trace_id`, `user_id`,
  `device_id`. No `print()`.
- Inject the clock (`core/clock.py`) so deadlines and hedging are testable.

### 1.1 Naming
| Thing | Style | Example |
|---|---|---|
| modules / functions | snake_case | `chains.py`, `resolve_target_device` |
| classes | PascalCase | `ChainRunner`, `ToolSpec` |
| tools | `<service>_<verb>[_<object>]` | `gmail_search`, `calendar_create_event`, `adb_open_app` |
| socket events | `domain.action` | `signal.final`, `tool.result`, `wake.claim` |
| settings | `UPPER_SNAKE` env → `Settings` fields | `PAID_PROVIDERS_ENABLED` |

## 2. Tools

```python
from app.tools.spec import ToolSpec, ToolResult, Risk

class OpenAppInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app: str = Field(description="App name as the user said it, e.g. 'spotify'")
    device: str | None = Field(default=None, description="Target device name; omit for the origin device")

open_app = ToolSpec(
    name="app_open",
    title="Open app",
    description="Opens an installed app on a device. Use the user's wording for the app name; "
                "the device resolves it against its installed-app index.",
    input_model=OpenAppInput,
    output_model=AppOpened,
    target="device",
    risk=Risk.WRITE,              # reversible
    annotations={"read_only": False, "destructive": False, "idempotent": True, "open_world": False},
    parallel_safe=True,
    requires={"apps"},
    timeout_s=5,
)
```

Rules:
- Workflow-shaped and namespaced; return readable fields, not raw ids; support `response_format`.
- Fail with `ToolResult.error(code, message)` where the message tells the model how to recover.
- Empty results are success with empty data. Never pad.
- Outputs over the cap → `artifacts.store(...)` + preview + handle.
- One test per tool with a fake client (`TESTING.md` §2).

## 3. LLM calls

```python
async for chunk in chains.stream(role="reflex", messages=msgs, tools=quick_tools, trace=trace):
    ...
```
- Only through `brain/app/llm/chains.py` with a role (`reflex`, `agent`, `subagent`, `vision`,
  `extract`). Never import a provider SDK in feature code.
- Prompts live in `agent/prompts/`: static prefix (persona block, rules, tools in deterministic
  order) first, volatile context last.
- Parse structured output into Pydantic models; on failure, retry once with the validation error,
  then escalate via the chain.

## 4. Latency-sensitive code (reflex path, gateway, body ear/mouth)

- No synchronous I/O, no unbounded loops, no per-request client construction.
- Every await on the network has `asyncio.timeout(...)`.
- Prefer streaming APIs; emit the first useful byte as early as possible.
- Register stage deadlines with the supervisor (`supervisor.expect(stage, deadline_ms)`).
- A hot-path PR includes before/after numbers from the latency bench.

## 5. Errors

- Classify: `user_fixable` (reconnect, permission), `retryable` (timeout, 429, 5xx),
  `bug` (validation, invariant). Retryable → chain or engine fallback; user-fixable → ask or
  connect card; bug → explained failure + incident + log with `exc_info`.
- User-facing text comes from persona templates (`PERSONA.md`), never `str(exc)`.
- Never swallow `asyncio.CancelledError`.

## 6. TypeScript (electron)

- `strict` mode; no `any` without a comment saying why.
- Main process: services in `src/main/` (BrainSocket, BodyBridge, TokenStore, Windows); IPC handlers
  validate every argument; the renderer reaches main only through `preload`.
- Renderer: function components + hooks; server state flows socket → Redux slices; every list and
  detail view handles loading / empty / error; copy follows `PERSONA.md`.
- `shell.openExternal` only for http(s) URLs; never `eval`, never remote code.

## 7. Tests

- Name scenario tests after their matrix id: `test_e1_open_youtube_on_phone`.
- Use the fakes and the controllable clock; no sleeps, no real network.
- Assert on behavior the user sees (events, speech deltas, timing), not internal calls.

## 8. Comments & docs

Explain *why*, not *what*. Platform workarounds name the failure they prevent. Delete dead code,
don't comment it out. Contract changes update `API.md` / `DATABASE.md` in the same commit.
