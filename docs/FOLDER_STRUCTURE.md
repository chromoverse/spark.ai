# FOLDER_STRUCTURE.md — Repository Layout (v2)

Single git repo. Each runnable part has its own environment. v1 layout: `legacy/FOLDER_STRUCTURE_v1.md`.

```
ai_local/
├── CLAUDE.md                 AI session rules → points to docs/
├── README.md                 setup & run
├── docs/                     this documentation (legacy/ holds v1 references)
├── deploy/                   docker-compose.yml, docker-compose.test.yml, Caddyfile, .env.example
├── scripts/                  setup / run-dev helpers
│
├── brain/                    cloud FastAPI brain
│   ├── pyproject.toml        deps pinned via uv lock
│   ├── app/
│   │   ├── main.py           app factory, lifespan, routers, socket mount
│   │   ├── core/             config, logging, security (jwt, crypto), errors, clock
│   │   ├── db/               SQLAlchemy models, session, alembic/
│   │   ├── auth/             otp, google, sessions, devices
│   │   ├── gateway/          Socket.IO /v2 handlers, presence, wake arbitration, sync log
│   │   ├── router/           tier-1 brain router (no-LLM intents, status, approvals) (§27)
│   │   ├── agent/            reflex.py, loop.py, subagents.py, context.py, prompts/ (persona block)
│   │   ├── llm/              openai_compat.py, claude.py (Anthropic SDK), chains.py (+ hedging), health.py, types.py
│   │   ├── supervisor/       per-user watcher, playbook, grounding check, incidents (§19)
│   │   ├── tools/            spec.py, registry.py, permissions.py, reviewer.py, brain tools
│   │   ├── capabilities/     skills/, plugins/, mcp/, hooks/ (§20)
│   │   ├── integrations/     google/, slack/, notion/, places/, search/ (SearXNG, ddgs, fetcher)
│   │   ├── research/         query planning, passage selection, citations (§22.2)
│   │   ├── memory/           extract.py, store.py, retrieve.py, embed.py (local ONNX)
│   │   ├── jobs/             runtime.py, scheduler.py, queue.py (offline-device queue)
│   │   ├── artifacts/        store, signed URLs, chart specs (§22.3)
│   │   └── api/              HTTP routes (API.md §2)
│   ├── evals/                reflex, agent, reflex_arc, research, persona suites
│   └── tests/                unit, integration, scenario, chaos; fakes/ (TESTING.md §2)
│
├── body/                     spark-body: Python sidecar on the device
│   ├── pyproject.toml
│   ├── spark_body/
│   │   ├── rpc.py            stdio JSON-RPC with Electron main (API.md §4)
│   │   ├── ear/              wake word, VAD, STT engines
│   │   ├── mouth/            TTS engines (Orpheus, edge-tts, Pocket/Kokoro/Chatterbox, Piper), playback, barge-in
│   │   ├── reflex_arc/       tier-0 grammar + classifier + phrase bank (§27)
│   │   ├── hands/            system, apps, files, shell, input, screen, browser (CDP), adb
│   │   ├── fitness/          hardware scan, engine benchmarks, engine plan (§18)
│   │   ├── watchdog.py       device-side supervisor (§19)
│   │   ├── sandbox/          workflow-mode Python sandbox, document/media parsers
│   │   ├── local_brain/      llama.cpp runner, model manager, fallback tool loop (§11)
│   │   └── mcp_local/        stdio MCP servers hosted on the device
│   └── tests/
│
├── electron/                 desktop shell + UI
│   ├── src/main/             windows, tray, IPC, BrainSocket, BodyBridge (stdio), keychain
│   ├── src/renderer/
│   │   ├── pages/            Home, Activity, Capabilities, Engines, Settings, Onboarding
│   │   ├── components/ui/    shadcn primitives
│   │   ├── components/spark/ conversation, job panel, approval modal, connect card, artifacts, palette
│   │   ├── store/            Redux Toolkit slices
│   │   └── hooks/
│   └── e2e/                  Playwright-for-Electron tests
│
└── (legacy, deleted phase by phase) server/, voice_daemon/, llms/,
    electron/action_executor/, electron/python-service/
```

## Where new code goes

| Adding… | Put it in |
|---|---|
| A brain tool | `brain/app/tools/` or `brain/app/integrations/<service>/` with a `ToolSpec` |
| A device tool | spec in `brain/app/tools/device_specs.py`, implementation in `body/spark_body/hands/` |
| A tier-0 intent | `body/spark_body/reflex_arc/` (grammar + examples + negative examples + phrases) and an eval row |
| An LLM provider | an entry in `brain/app/llm/chains.py` (OpenAI-compatible) and an eval run |
| A TTS/STT engine | `body/spark_body/mouth/` or `ear/` implementing the engine interface + a fitness probe |
| An HTTP route | `brain/app/api/` + `API.md` §2 |
| A socket event | `brain/app/gateway/` + `API.md` §3 |
| A table / column | `brain/app/db/` + Alembic migration + `DATABASE.md` |
| A built-in skill | `brain/app/capabilities/skills/builtin/<name>/SKILL.md` |
| A UI page or component | `electron/src/renderer/pages/` or `components/spark/` + `DESIGN.md` |
| A scenario | a row in `TESTING.md` §4 + a test in `brain/tests/scenario/` |

## Ownership rule

`brain/`, `body/`, and `electron/` never import each other. They talk only over the contracts in
`API.md` (socket, HTTP, stdio JSON-RPC).
