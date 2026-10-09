# FOLDER_STRUCTURE.md — Repository Layout

> **v1 (legacy) reference.** This describes the current `server/` + `voice_daemon/` + `llms/` code.
> The target design is **`REDESIGN.md`** (v2). Sections here are replaced as v2 phases land.

Single git repo. Each runnable part has its own virtualenv and env file.

```
ai_local/
├── CLAUDE.md                  AI session rules (graphify) → points here
├── README.md                  setup & run
├── docs/                      this documentation set
├── scripts/                   setup.{ps1,sh}, run-dev.{ps1,sh}
├── graphify-out/              code knowledge graph (ignored, rebuilt by post-commit hook)
│
├── server/                    FastAPI backend
│   ├── main.py                entry: uvicorn app.main:app (127.0.0.1:PORT)
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py            FastAPI app, lifespan, CORS, router + socket mount
│   │   ├── config.py          Settings (env)
│   │   ├── startup_registrations.py / auto_initializer.py   startup initializers
│   │   ├── api/routes/        HTTP routes (auth, chat, system, kernel, stt, tts, drive, debug)
│   │   ├── socket/            Socket.IO server + handlers (chat_utils, task_handler, tts_handler)
│   │   ├── services/
│   │   │   ├── chat/          PQH (chat_service), SQH (sqh_service), stream, clarification, summaries
│   │   │   ├── tts/ stt/      speech engines
│   │   │   ├── scheduler/     cron/reminder jobs (SQLite)
│   │   │   ├── activity/      activity log (SQLite)
│   │   │   └── shell/         shell execution service
│   │   ├── kernel/
│   │   │   ├── execution/     orchestrator, execution engine, approvals, bindings, replanner
│   │   │   ├── persistence/   task/tool stats (Mongo)
│   │   │   ├── observability/ structured logging, log index
│   │   │   ├── eventing/ contracts/ runtime/
│   │   ├── agent/runtime/     context services, meta-query router
│   │   ├── ai/providers/      provider clients, router, routing_config, key_manager
│   │   ├── prompts/           PQH/SQH/stream prompts, tool categories
│   │   ├── connectors/        OAuth flow, MCP, connector registry, middleware
│   │   ├── features/          external_service (token encryption), gmail, bridge
│   │   ├── memory/            user profile, background learning, keyword index
│   │   ├── cache/             local KV, LanceDB, Upstash, sync
│   │   ├── db/                Mongo client, indexes, Pinecone
│   │   ├── models/ schemas/   Pydantic models
│   │   ├── path/              PathManager, artifacts
│   │   ├── jwt/ dependencies/ auth
│   │   ├── ml/                embeddings, emotion, whisper loaders
│   │   └── emails/            Resend templates (OTP)
│   ├── plugins/
│   │   ├── manager.py         discovery + loading
│   │   ├── skills/            skill engine
│   │   └── installed/<plugin>/{plugin.json, tools/, skills/}
│   │        ai · google · media · notion · slack · spark · system · web (browser agent lives in web/browser)
│   ├── tools/                 legacy tool tree + registry files (migrating into plugins)
│   ├── shared/                path_resolver, process_manager, searcher
│   ├── tests/                 unit tests (CI) · tests/manual/ (live, not in CI)
│   ├── testing/               legacy scripts & e2e (to be sorted, Phase 1)
│   └── scripts/               maintenance scripts (encrypt_secrets, migrations)
│
├── electron/                  desktop app
│   ├── src/main/              main process: windows/, ipc/, services/, utils/, preload.cts
│   ├── src/renderer/          React: pages/, components/{ui,local}/, store/, hooks/, context/
│   ├── src/types/             shared TS types
│   ├── action_executor/       Python client-side tool executor (spawned by main)
│   ├── python-service/        legacy, unreferenced (see MEMORY.md)
│   ├── electron-builder.json
│   └── package.json
│
├── voice_daemon/              wake word + VAD + streaming + playback
│   ├── main.py
│   ├── core/  (mic, vad, wake_word, state)
│   ├── stream/ (chunker, socket_client, poster)
│   ├── playback/ (ding, tts_player)
│   ├── health/ (server_watch)
│   ├── config/ models/ scripts/ tests/
│
└── llms/                      optional local LLM (llama.cpp) service
    ├── run.py  model_config.json
    └── app/{api/v1/llm, core, services}
```

## Where New Code Goes

| Adding… | Put it in |
|---|---|
| A tool | `server/plugins/installed/<plugin>/tools/<tool>.py` + list it in `plugin.json` |
| A multi-tool recipe | `server/plugins/installed/<plugin>/skills/<name>.yaml` |
| A new integration | new plugin folder; OAuth provider config in `app/features/external_service/providers.py` |
| An HTTP route | `server/app/api/routes/<area>.py`, registered in `routes/__init__.py::ROUTE_MODULES` |
| A socket event | the matching handler module in `server/app/socket/` |
| An LLM provider | `server/app/ai/providers/<name>_client.py` + `routing_config.py` + `key_manager.py` |
| A filesystem path | a field on `PathManager` layout, never a literal path |
| A client (desktop) tool | `electron/action_executor/tools/` + `registry/tool_registry.json` |
| A UI page | `electron/src/renderer/pages/home/<Name>Page.tsx` |
| A shared UI primitive | `electron/src/renderer/components/ui/` (shadcn) |

## Ownership Rule

Each folder owns its runtime: no imports across `server/`, `electron/`, `voice_daemon/`, `llms/`.
They talk over HTTP/Socket.IO only. Shared contracts are documented in `API.md`.
