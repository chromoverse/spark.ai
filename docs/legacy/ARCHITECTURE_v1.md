# ARCHITECTURE.md — System Architecture & Flows

> **v1 (legacy) reference.** This describes the current `server/` + `voice_daemon/` + `llms/` code.
> The target design is **`REDESIGN.md`** (v2). Sections here are replaced as v2 phases land.

## 1. Processes

Spark is four processes on one machine. Only the server and the Electron app are required.

```
┌────────────────────┐   Socket.IO + HTTP    ┌─────────────────────────────┐
│ Electron app       │◄─────────────────────►│ Server (FastAPI, :8000)     │
│ main + renderer    │   JWT (access token)  │ 127.0.0.1 only              │
│  └ action_executor │                       │  ├ chat pipeline (PQH/SQH)  │
│    (Python child)  │◄── task:execute ──────│  ├ kernel (orchestrator,    │
└────────────────────┘── task:result ───────►│  │  execution engine)       │
                                             │  ├ plugins (≈97 tools)      │
┌────────────────────┐   Socket.IO           │  ├ connectors (OAuth, MCP)  │
│ Voice daemon       │◄─────────────────────►│  ├ scheduler, activity log  │
│ wake word + VAD    │ DAEMON_SERVICE_TOKEN  │  └ TTS / STT engines        │
└────────────────────┘                       └──────┬──────────────┬───────┘
                                                    │              │
┌────────────────────┐   HTTP (optional)            │              │
│ Local LLM (:9001)  │◄─────────────────────────────┘              │
│ llama.cpp wrapper  │                         MongoDB, local SQLite/LanceDB,
└────────────────────┘                         cloud LLM providers, Google/Slack/Notion
```

| Process | Entry point | Port | Runtime |
|---|---|---|---|
| Server | `server/main.py` → `app.main:app` | 8000 (`PORT`) | `server/.venv` |
| Electron | `electron/src/main/main.ts` | Vite 5123 in dev | Node + `electron/.venv` for the executor |
| Action executor | `python -m action_executor.electron_bridge` (spawned by `ActionExecutorService.ts`) | stdio | `electron/.venv` |
| Voice daemon | `voice_daemon/main.py` | — | `voice_daemon/.venv` |
| Local LLM | `llms/run.py` | 9001 | `llms/.venv` |

**Windows event loop:** `main.py` and `app/main.py` force `ProactorEventLoop` so Playwright can
spawn subprocesses under Uvicorn reload. Do not remove it.

## 2. Server Startup (`app/main.py` lifespan)

1. `run_all_initializers()` — registered in `app/startup_registrations.py` (cache, API keys, TTS,
   ML/embedding models, agent system, tool registry)
2. Mongo connect + `create_indexes()`
3. `init_socket()` — registers chat, task, TTS socket handlers
4. Scheduler start
5. `PluginManager.discover_and_load()` — scans `server/plugins/installed/*/plugin.json`

Shutdown reverses it: kernel persistence flush, scheduler, activity log, MCP servers, browser
session (CDP), Mongo, ML models, thread executor.

## 3. Request Pipeline

```
send-user-text-query / voice (STT)
        │
        ▼
_parallel_execute (socket/chat_utils.py)
        │
        ├── PQH  services/chat/chat_service.py
        │     system prompt (pqh_prompt_v2) + last 5 turns + query
        │     → PQHResponse { answer, emotion, cognitive_state, requested_tool[] }
        │     → spoken reply streamed immediately (stream_service + TTS)
        │
        ├── Clarification (clarification_service) if needs_clarification
        │
        └── SQH  services/chat/sqh_service.py   (background task)
              ├── SkillEngine match → expand YAML recipe → tasks (no LLM)
              └── else LLM plan (sqh_prompt) → Task[] with depends_on + input_bindings
                      │
                      ▼
              kernel/execution/orchestrator.py  (TaskOrchestrator, DAG)
                      │  approval_coordinator, resource_lock, cancellation,
                      │  job_coordinator, replanner, failure_classifier
                      ▼
              kernel/execution/execution_engine.py
                      ├── server tool → server_executor → BaseTool.execute()
                      └── client tool → task_emitter → Electron "task:execute"
                                          ← "task:result"
                      ▼
              task:progress / task:summary / tool:output events → UI
              task_summary_speech_service → spoken summary
```

Meta-queries ("what can you do", "what tools do you have") are short-circuited by
`app/agent/runtime/meta_query_router.py` before PQH.

### 3.1 Task bindings
Tasks reference earlier outputs via `input_bindings` resolved by `binding_resolver.py`
(JSONPath, with flat-key fallback). Outputs are isolated per job: a task can only bind to tasks
in its own job.

### 3.2 Failure handling
`failure_classifier.py` labels errors (auth, quota, invalid input, transient). Transient errors
retry; recoverable plan errors go to `replanner.py`; user-facing text comes from
`failure_messages.py`. Tool outputs must never claim success the data doesn't support (see
`MEMORY.md` → calendar/Gmail bugs).

## 4. LLM Provider Routing

`app/ai/providers/router.py` + `routing_config.py`. Each use case has an ordered provider chain;
the first provider with a valid key and no tripped quota wins, then `UNIVERSAL_FALLBACK`.

| Use case | Chain (priority order) |
|---|---|
| `streaming` (PQH, SQH, chat) | anthropic `claude-opus-5-5` → cerebras → groq → gemini |
| `reasoning` | cerebras qwen-3-235b → sambanova DeepSeek-V3.2 |
| `lightweight` | groq llama-3.1-8b → cerebras llama3.1-8b |
| `content_generate` | sambanova → gemini |
| `summarize` | mistral → groq |
| `entity_extract` | groq → mistral → cerebras |

Keys: user keys (Mongo `users.api_keys`, activated on socket connect) take priority over system
keys (env / Windows registry). Multiple keys per provider rotate. See
`server/app/ai/providers/guide.md`. `INFERENCE_MODE=local` routes to the `llms/` service.

## 5. Environments

| `ENVIRONMENT` | Cache backend | Vectors | Local ML models | Intended use |
|---|---|---|---|---|
| `DESKTOP` (default) | SQLite local KV | LanceDB | loaded | Shipped desktop app |
| `DEVELOPMENT` | Redis/Upstash | — | skipped | Server dev |
| `PRODUCTION` | Upstash | Pinecone | skipped | Hosted server (not a v1 target) |

## 6. Data & Storage

Detail in `DATABASE.md`. Summary:

- **MongoDB** — users, chats, memory, oauth_tokens, user_profiles, kernel stats (task_runs,
  tool_invocations, tool_daily_aggregates, kernel_events)
- **App-data dir** (`PathManager`): Windows `%LOCALAPPDATA%\SparkAI`, macOS
  `~/Library/Application Support/SparkAI`, Linux `~/.local/share/SparkAI`
  - `db/kvstore.db`, `db/scheduler.db`, `db/activity.db` (SQLite)
  - LanceDB vectors, `logs/server-<startup_id>.jsonl`, artifacts (screenshots, documents, exports, media)
  - `config.json` (shared with the voice daemon: wake word settings)

`app/path/manager.py` is the only place that allocates paths. New code uses `PathManager().layout`.

## 7. Plugin System

`server/plugins/` — see `server/plugins/README.md`.

```
plugins/installed/<name>/
  plugin.json        name, version, capabilities, tools[], skills[]
  tools/*.py         BaseTool subclasses (one tool = one verb)
  skills/*.yaml      optional multi-tool recipes
```

Tools register into the in-memory `ToolRegistry`; the registry also loads legacy tools from
`server/tools/`. Tool metadata (schemas, category, server vs. client target) comes from the
registry files under `server/tools/registry/`.

## 8. Connectors

- **OAuth** (`app/connectors/oauth/flow.py`, prefix `/auth`): Google (Gmail, Calendar, Drive),
  Slack, Notion. Refresh tokens encrypted with `TOKEN_ENCRYPTION_KEY` and stored in `oauth_tokens`.
- **MCP** (`app/connectors/mcp/`): external MCP servers from `servers.json`, adapted into tools.
- **Connector registry** (`app/connectors/router.py`, prefix `/connectors`): list, status, capabilities.

## 9. Real-Time Events

Socket.IO at `/socket.io`. Auth at connect: user JWT, or `client_type: "daemon"` with
`DAEMON_SERVICE_TOKEN`. One user can have many sockets (`connected_users: user_id → {sid}`).
Event catalog in `API.md` §4.

## 10. Voice Path

```
mic → openWakeWord ("hey spark"/"spark") → ding → Silero VAD → 20 ms chunks
   → Socket.IO (user-speaking / user-stop-speaking) → server STT (Groq Whisper)
   → pipeline (§3) → response-tts chunks → daemon tts_player
user-interrupt / speech during playback → tts-interrupt
```

Speculative pre-fetch: while the user is still speaking, the server warms user context
(`speculative_cache`) to cut first-response latency. See `latency.md`.

## 11. Electron

- **Main** (`src/main`): windows (main, secondary, tray), IPC handlers, `SocketService`,
  `TokenManager` (keytar), `ActionExecutorService` (spawns Python executor), `DeviceStatusService`
- **Preload** (`preload.cts`): the only bridge; `contextIsolation: true`, `nodeIntegration: false`
- **Renderer** (`src/renderer`): React 19 + Redux Toolkit, pages under `pages/` and `pages/home/`
- **Client tools**: `electron/action_executor` (registry `registry/tool_registry.json`, 20 tools)

## 12. Background Jobs

| Job | Where | Notes |
|---|---|---|
| User scheduler (reminders, cron tasks) | `services/scheduler` | croniter, SQLite-persisted |
| Cache sync (local → cloud) | `cache/sync_manager.py` | `CACHE_SYNC_*` settings |
| Background learning | `memory/background_learning.py` | builds user profile from chats |
| Artifact cleanup | `path/artifact_cleanup.py` | retention of tool artifacts |
| STT session + speculative cache cleanup | `socket/chat_utils.py` | started at socket init |

## 13. Packaging & Deployment

Target: a single installer per OS, embedded Python, server + daemon registered as services,
Electron auto-start, auto-update via GitHub Releases. Full blueprint: `PRODUCTION.md`.
Current `electron/electron-builder.json` only packages the renderer and main bundle; it does
not yet ship the server, daemon, or a Python runtime (Phase 3 in `PHASES.md`).
