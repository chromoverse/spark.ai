# DATABASE.md — Data Stores & Schemas

> **v1 (legacy) reference.** This describes the current `server/` + `voice_daemon/` + `llms/` code.
> The target design is **`REDESIGN.md`** (v2). Sections here are replaced as v2 phases land.

Spark uses MongoDB for user-scoped durable data and local files under the app-data directory for
machine-scoped state. Indexes live in `server/app/db/indexes.py`; Pydantic models in
`server/app/models/`.

## Conventions

- Field names are `snake_case` in Mongo; API models use `CamelModel` for camelCase output.
- `user_id` is the string form of `users._id`.
- Timestamps are UTC (`datetime.now(timezone.utc)`; legacy code uses `utcnow()`, migrate when touched).
- Secrets (OAuth refresh tokens, provider keys) are encrypted at rest. **Provider keys in
  `users.api_keys` are currently plaintext** — Phase 0.
- Every query on user data filters by `user_id` taken from the verified token.

---

## 1. MongoDB (`DB_NAME`, default `spark`)

### users — `models/user_model.py::UserModel`
| Field | Type | Notes |
|---|---|---|
| `_id` | ObjectId | |
| `email` | str | login identity (not yet uniquely indexed — add) |
| `username`, `full_name`, `gender` | str? | |
| `is_user_verified` | bool | |
| `verification_token`, `verification_token_expires` | str?, datetime? | current OTP (plaintext; hash it) |
| `refresh_token` | str? | current refresh token, never exposed |
| `api_keys` | `{provider: [key]}` | user provider keys. **Plaintext today; returned by `UserResponse`** |
| `language`, `ai_gender`, `ai_voice_name`, `theme`, `notifications_enabled` | prefs | |
| `personal_memories`, `reminders`, `liked_items`, `disliked_items`, `behavioral_tags`, `activity_habits` | lists/dicts | personalization |
| `is_gemini_api_quota_reached`, `is_openrouter_api_quota_reached` | bool | quota flags |
| `utm_*`, `advertiser_partner` | str? | attribution |
| `created_at`, `last_login`, `last_active_at`, `session_count` | | |
| `custom_attributes`, `preferences_history` | | |

Indexes needed: `email` unique (missing).

### chats — `models/chat_model.py`
| Field | Type |
|---|---|
| `user_id` | str |
| `message` | str |
| `created_at` | datetime |

Index: `(user_id, created_at desc)`.

### memory
User memories with `user_id`, `importance`. Indexes: `user_id`, `importance`.

### user_profiles — `memory/user_profile.py`
Learned profile per `user_id` (background learning output).

### oauth_tokens — `models/oauth_model.py::OAuthTokenModel`
| Field | Type | Notes |
|---|---|---|
| `user_id` | str | |
| `service` | str | `gmail`, `google_calendar`, `google_drive`, `slack`, `notion`, … |
| `account_email` | str? | which account was connected |
| `refresh_token` | str | AES-encrypted with `TOKEN_ENCRYPTION_KEY` |
| `scope` | str? | |
| `is_active` | bool | |
| `connected_at`, `last_refreshed` | datetime | |

Index: unique `(user_id, service, account_email)`.

### Kernel stats — `kernel/persistence/stats_store.py`
| Collection | Content |
|---|---|
| `task_runs` | one doc per task execution (status, timings, job) |
| `tool_invocations` | per-tool call records |
| `tool_daily_aggregates` | per-day rollups for metrics |
| `kernel_events` | job/task lifecycle events |

No indexes or TTLs defined yet. Add `(user_id, created_at)` indexes and a retention TTL (Phase 1).

---

## 2. Local stores (app-data dir, via `PathManager`)

| Store | Path | Owner | Content |
|---|---|---|---|
| Local KV | `db/kvstore.db` (SQLite) | `cache/local_kv_manager.py` | cache in DESKTOP mode, OAuth PKCE verifiers (10 min TTL) |
| Scheduler | `db/scheduler.db` (SQLite) | `services/scheduler/persistence.py` | scheduled jobs |
| Activity log | `db/activity.db` (SQLite) | `services/activity/store.py` | user-visible activity feed |
| Vectors | LanceDB dir | `cache/lancedb_manager.py` | chat/memory embeddings (DESKTOP) |
| Logs | `logs/server-<startup_id>.jsonl` | `kernel/observability/log_index.py` | structured server logs |
| Artifacts | `artifacts/{records,screenshots,documents,exports,media}` | `path/artifacts.py` | tool outputs |
| Shared config | `config.json` | server + voice daemon | wake word, device settings |

Electron stores the auth token in the OS keychain via `keytar`; renderer state is Redux in memory.

## 3. Cloud stores

| Store | When | Notes |
|---|---|---|
| Upstash Redis | `DEVELOPMENT` / `PRODUCTION` | cache backend (`CACHE_PROD_BACKEND`) |
| Pinecone | `PRODUCTION` | vectors, integrated embeddings |

## 4. Change process

A new collection, field, or index is documented here in the same commit. Destructive migrations
need a script under `server/scripts/` and a `CHANGELOG.md` note.
