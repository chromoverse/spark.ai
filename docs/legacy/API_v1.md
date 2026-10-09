# API.md — HTTP & Socket.IO Contracts

> **v1 (legacy) reference.** This describes the current `server/` + `voice_daemon/` + `llms/` code.
> The target design is **`REDESIGN.md`** (v2). Sections here are replaced as v2 phases land.

Base URL (dev): `http://127.0.0.1:8000`. Renderer uses `VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1`
and `VITE_API_SOCKET_URL=http://127.0.0.1:8000`.

Interactive schema: `GET /docs` (FastAPI OpenAPI).

> **Auth status legend** — 🔒 requires a verified access token · ⚠️ **unauthenticated and trusts a
> client-supplied `user_id`** (Phase 0 blocker, see `PHASES.md` §0) · 🌐 public by design ·
> 🧪 debug/dev only (must not be mounted in production builds)

---

## 1. Conventions

### 1.1 Response envelope (`app/helper/response_helper.py`)

```json
{ "success": true,  "message": "Success", "data": { } }
{ "success": false, "message": "Human-readable reason", "errors": { } }
```

Older routes (kernel, connectors, system) return raw dicts. New routes use the envelope.

### 1.2 Auth transport

- Access token (JWT HS256, 30 min) and refresh token (7 days), issued by `/api/v1/auth/verify-otp`.
- Electron clients (User-Agent contains `electron`) receive tokens in the body; browsers get
  `httponly` cookies.
- Server reads the token from cookie `access_token`, `Authorization: Bearer <jwt>`, or
  `?access_token=` (`app/dependencies/auth.py::get_current_user`).
- Socket.IO: `io(url, { auth: { token } })`. Daemon: `auth: { token: DAEMON_SERVICE_TOKEN, client_type: "daemon" }`.

### 1.3 Status codes

| Code | Meaning |
|---|---|
| 400 | Validation / bad input |
| 401 | Missing, invalid, or expired token |
| 403 | Wrong token type (refresh used as access) |
| 404 | Not found |
| 429 | Provider quota (surfaced from LLM providers) |

### 1.4 Rule for new endpoints
Resolve the user with `Depends(get_current_user)` and use `request.state.user["_id"]`. Never
accept `user_id` as a query/body parameter.

---

## 2. Auth — `/api/v1/auth` (`app/api/routes/auth.py`)

| Method | Path | Auth | Body / Query | Notes |
|---|---|---|---|---|
| POST | `/register` | 🌐 | `{ email }` | Creates or re-uses user, emails 6-digit OTP |
| POST | `/verify-otp` | 🌐 | `{ email, otp }` | Returns access + refresh token. ⚠️ no attempt limit |
| POST | `/sign-in` | 🌐 | `{ email }` | Sends login OTP |
| POST | `/refresh-token` | 🌐 | `{ refresh_token }` | Rotates refresh token |
| POST | `/insert-api-keys` | 🔒 | `{ <provider>: [keys] }` | Stores user provider keys |
| PATCH | `/update-user-details` | 🔒 | `UserUpdateQuery` | Preferences, profile |
| GET | `/get-me` | 🔒 | — | Current user |
| GET | `/get-users` | ⚠️ | — | Lists all users. Broken (returns a cursor). Delete |
| GET | `/load_user` | ⚠️ | `?user_id=` | Returns full user **including `api_keys`**. Delete or lock down |

## 3. Other HTTP routes

### 3.1 System (`routes/system.py`)
| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/` | 🌐 | Banner |
| GET | `/health` | 🌐 | Liveness. Used by daemon/Electron health polling |
| GET | `/ml/status` | 🌐 | Embedding/ML readiness |
| GET | `/orchestration/status` | 🌐 | Orchestrator state |
| GET | `/quota` | 🌐 | Provider quota summary (UI quota arc) |
| GET | `/runtime/dependencies` | 🌐 | Runtime dependency bootstrap status |

### 3.2 Chat, STT, TTS
| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | `/chat` | ⚠️ | `{ text, user_id }`. Runs the full pipeline **and executes tools** for any `user_id` |
| POST | `/api/stt` | ⚠️ | multipart `file` → transcript |
| POST | `/tts/stream` | ⚠️ | Streaming TTS |
| POST | `/tts/complete` | ⚠️ | Full TTS audio |

### 3.3 Kernel (`routes/kernel.py`, prefix `/kernel`)
| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/user-metrics` | ⚠️ | `?user_id&window=30d` |
| GET | `/user-history` | ⚠️ | `?user_id&window&cursor&limit≤200` |
| GET | `/user-logs` | ⚠️ | `?user_id&startup_id&level&cursor&limit≤500` |
| GET | `/tools/runtime-summary` | 🌐 | |
| GET | `/tools` | 🌐 | Tool catalog |
| GET | `/plugins` | 🌐 | Loaded plugins |
| GET | `/skills` | 🌐 | Skills |
| GET | `/permissions` | ⚠️ | Tool permission grants |
| POST | `/permissions/revoke` | ⚠️ | |

### 3.4 Drive (`routes/drive.py`)
| GET | `/api/v1/drive/read` | ⚠️ | Read a Drive file for a user |
|---|---|---|---|

### 3.5 OAuth connectors (`app/connectors/oauth/flow.py`, prefix `/auth`)
| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/{service}/connect` | ⚠️ | `?user_id`. Redirects to provider consent. `state = "<service>:<user_id>"` (no CSRF nonce) |
| GET | `/{service}/callback` | 🌐 | Provider redirect; stores encrypted refresh token |
| DELETE | `/{service}/disconnect` | ⚠️ | |
| GET | `/{service}/status` | ⚠️ | `{ service, connected }` |
| GET | `/internal/token/{service}` | ⚠️ | **Returns a live OAuth access token for any `user_id`.** Remove from HTTP; call the service function in-process |

`service` ∈ providers in `app/features/external_service/providers.py` (Google Gmail/Calendar/Drive, Slack, Notion).

### 3.6 Connector registry (`app/connectors/router.py`, prefix `/connectors`)
| GET | `/list` · `/{connector_id}/status` · `/{connector_id}/capabilities` | 🌐 |
|---|---|---|

### 3.7 Debug 🧪
`/ml-test/*` (embedding, emotion, whisper), `/debug/openrouter/*`. Gate behind
`ENVIRONMENT != DESKTOP` or a debug flag.

---

## 4. Socket.IO Events (`/socket.io`)

### 4.1 Client → Server
| Event | Payload | Handler |
|---|---|---|
| `send-user-text-query` | `{ query }` or string | `socket/chat_utils.py` |
| `user-speech-started` / `user-speaking` / `user-stop-speaking` | audio chunks + meta | `chat_utils.py` (STT session) |
| `user-interrupt` | — | stops TTS / current speech |
| `entity-card-action` | `{ action, entity, ... }` | entity card buttons |
| `agent:clarify:response` | `{ answer }` | resolves pending clarification |
| `task:result` | `{ task_id, result }` | `socket/task_handler.py` (client tool done) |
| `task:batch_results` | `[{ task_id, result }]` | |
| `task:approval:response` | `{ approval_id, approved }` | approval coordinator |
| `tool:output:get` / `tool:output:list` | `{ job_id, task_id? }` | fetch stored tool outputs |
| `request-tts` | `{ text, ... }` | `socket/tts_handler.py` |

### 4.2 Server → Client
| Event | Meaning |
|---|---|
| `query-result` / `query-error` | PQH result for a query |
| `response-tts`, `tts-start`, `tts-interrupt` | TTS audio stream lifecycle |
| `task:execute` / `task:batch` | Run a client-side tool in Electron |
| `task:progress`, `task:summary` | Live task progress and final summary |
| `task:approval:request` | Ask user to approve a sensitive task |
| `job:queued` · `job:started` · `job:promoted` · `job:replanning` · `job:resumed` · `job:completed` · `job:failed` | Job lifecycle |
| `tool:output`, `tool:outputs` | Tool result payloads (entity cards, files, etc.) |
| `tool_step`, `tool_params`, `tool_llm_call`, `tool_shell`, `tool_output` | Fine-grained tool detail stream |
| `agent:clarify:ack` | Clarification handled |
| `entity-card-action-result` | Result of an entity card action |
| `spark:log`, `spark:message` | Activity log stream / proactive messages |
| `notification`, `announcement` | User notifications |
| `registered` | Connection registered |

### 4.3 Task payload (`task:execute`)

```json
{
  "task": {
    "task_id": "uuid",
    "tool": "file_create",
    "inputs": { "path": "C:/tmp/a.txt", "content": "hello" },
    "depends_on": ["prev_task_id"]
  },
  "status": "pending"
}
```

---

## 5. Local LLM service (`llms/`, port 9001)

| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/llm/...` (generate, streaming) | See `llms/app/api/v1/llm/router.py` |
| POST | `/api/v1/llm/cancel` | Cancel in-flight generation |

Binds `HOST=0.0.0.0` by default; set `127.0.0.1` for desktop installs.
