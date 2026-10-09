# DATABASE.md — Data Model (v2)

Source of truth for the brain's Postgres schema, Redis keys, and device-local stores. Change this
file in the same commit as the Alembic migration. v1 (MongoDB) is in `legacy/DATABASE_v1.md`.

## Conventions

- Postgres 16 + `pgvector`. SQLAlchemy 2.0 async models in `brain/app/db/`, Alembic migrations.
- Primary keys: UUIDv7 (`id uuid`), time-sortable.
- Timestamps: `timestamptz`, UTC, `created_at` / `updated_at` on every table, except the
  append-only `events` and `audit_log`, which carry a single `ts`.
- Status: ✅ = created by a migration (`brain/app/db/alembic/versions/`). Everything else is planned.
- Deleting a user cascades to every row that references it (account deletion is a hard delete).
- Every user-owned row has `user_id` and every query filters by it (resolved from the token).
- Secrets are encrypted with AES-GCM under the master key (`ENCRYPTION_MASTER_KEY`); only
  ciphertext and `last4` are stored.
- Soft delete only where restore matters (`deleted_at`); account deletion is a hard delete.

## 1. Identity & devices

| Table | Columns | Indexes |
|---|---|---|
| ✅ `users` | id, email (citext, unique), name, nickname, plan (`free`), created_at, updated_at | `email` unique |
| ✅ `auth_identities` | id, user_id, provider (`email`/`google`), subject (email address or Google `sub`), created_at, updated_at | unique (provider, subject), (user_id) |
| ✅ `otp_codes` | id, email (citext), code_hash (HMAC-SHA256, peppered; never the code), attempts, expires_at, consumed_at, created_at, updated_at | (email, expires_at) |
| ✅ `sessions` | id, user_id, device_id, refresh_hash (SHA-256 of the current refresh secret), expires_at, revoked_at, last_used_at, created_at, updated_at | (user_id), (device_id), unique refresh_hash |
| ✅ `devices` | id, user_id, kind (`desktop`/`mobile`/`adb_phone`), name, platform, parent_device_id (ADB phones), capabilities jsonb (list), hardware jsonb, engine_plan jsonb, is_default_for text[], app_version, last_seen_at, created_at, updated_at | (user_id) |
| ✅ `user_settings` | user_id (pk), language (`en`), auto_detect_language, voice, verbosity (`brief`/`normal`/`detailed`), address_as, permission_mode (`default`/`ask`/`trust`, REDESIGN §7.2), allow_training_providers, models jsonb, created_at, updated_at | — |

## 2. Conversation & work

| Table | Columns | Indexes |
|---|---|---|
| ✅ `threads` | id, user_id, title, last_message_at, created_at, updated_at | (user_id, last_message_at desc) |
| ✅ `messages` | id, thread_id, user_id, role, content jsonb (content blocks), tier (0–3), device_id (set null on device delete), signal_id, created_at, updated_at | (thread_id, created_at), (user_id) |
| `jobs` | id, user_id, thread_id, status, effort, todo jsonb, eta_s, provider_used, usage jsonb, created_at, finished_at | (user_id, created_at desc), partial on active status |
| `job_steps` | id, job_id, tool, input jsonb, output_ref, status, device_id, started_at, finished_at, error | (job_id) |
| `approvals` | id, user_id, job_id, tool, inputs_preview jsonb, decision, decided_by_device, created_at | (user_id, created_at) |
| `artifacts` | id, user_id, thread_id, kind, storage_ref, preview jsonb, meta jsonb, created_at | (user_id, thread_id) |
| `schedules` | id, user_id, cron, run_at, payload jsonb, next_run_at, last_run_at, enabled | (next_run_at) where enabled |
| `queued_actions` | id, user_id, target_device_id, tool_call jsonb, expires_at | (target_device_id) |

## 3. Memory

| Table | Columns | Indexes |
|---|---|---|
| `memories` | id, user_id, kind (`preference`/`person`/`routine`/`fact`/`correction`), text, embedding vector(384), tsv tsvector, importance real, confirmed bool, source_message_id, last_used_at, expires_at | HNSW (embedding vector_cosine_ops); GIN (tsv); (user_id) |
| `profiles` | user_id (pk), summary text (≤ 300 tokens), updated_at | — |

## 4. Capabilities & access

| Table | Columns |
|---|---|
| `permission_rules` | id, user_id, device_id?, tool, pattern, decision (`deny`/`ask`/`allow`), created_at |
| `skills` | id, user_id, name, description, source (`builtin`/`import`/`plugin`), storage_ref, enabled, version |
| `plugins` | id, user_id, name, marketplace, version, trust_tier, enabled, context_cost_tokens |
| `mcp_servers` | id, user_id, name, url, transport, trusted, approval_mode, oauth_ciphertext, enabled |
| `api_keys` | id, user_id, provider, ciphertext, last4, is_free_tier, created_at |
| `oauth_connections` | id, user_id, service, account_email, refresh_ciphertext, scopes text[], status, updated_at |

## 5. Operations

| Table | Columns | Notes |
|---|---|---|
| `usage_events` | id, user_id, role, provider, model, input_tokens, output_tokens, cache_tokens, audio_s, cost_micros, paid bool, ts | (user_id, ts); monthly partitions |
| ✅ `incidents` | id, user_id, device_id (set null on device delete), stage (`llm`/`tool`/`tts`/`stt`/`wake`/`vad`/`local_llm`/`deadline`/`brain`), engine_or_provider, error, remedy (`bridge`/`switch`/`replan`/`explain`/…), outcome (`recovered`/`failed_explained`/`degraded`), signal_id, ts | (user_id, ts); 90 days |
| ✅ `events` | seq (bigint identity, pk; sent to devices as the event `id`), user_id, type, payload jsonb, ts | sync log, 7-day retention, (user_id, seq) |
| ✅ `audit_log` | id, user_id, actor (`user`/`device:<id>`/`system`), action, target, meta jsonb, ts | append-only, (user_id, ts) |

## 6. Redis keys

| Key | Value | TTL |
|---|---|---|
| `presence:{user}` | ✅ hash device_id → last ping (epoch ms), written on connect/hello and every 30 s; an entry older than 60 s counts as offline | 60 s |
| `hot:{user}:turns` | last N messages | 1 h |
| `hot:{user}:profile` | profile summary + settings | 1 h |
| `prefetch:{signal}` | retrieved memories for an in-flight signal | 30 s |
| `health:{provider}:{key}:{model}` | ✅ `open_until` (circuit), `fails` (consecutive), `ttft_ms` (EWMA), `last_error`; `{key}` is an 8-char hash prefix of the API key | 24 h |
| `rl:{scope}:{id}` | request counter (fixed window; R0 scopes: `otp_start`, `otp_verify`, `refresh`, `google_start`, `google_exchange`, keyed by IP) | per window |
| `oauth:google:state:{state}` | sign-in flow: nonce, PKCE challenge, loopback port, device info | 10 min, deleted on use |
| `oauth:google:login:{code}` | Google identity waiting for the app's PKCE exchange | 60 s, deleted on use |
| `wake:{user}:{window}` | arbitration claims | 2 s |
| `signal:{user}:{signal_id}` | ✅ dedupe marker: a repeated `signal.final` / `signal.handled_locally` runs once | 5 min |
| `phrase:{user}:{moment}` | ✅ last phrase-bank line used for that moment, so it never repeats twice in a row | 1 h |
| `cache:tool:{tool}:{hash}` | idempotent tool result (weather, places) | per tool (10 min – 1 day) |

## 7. Device-local stores (`spark-body`, under `%LOCALAPPDATA%\SparkAI`)

| Store | Content |
|---|---|
| `fitness.db` (SQLite) | benchmark history, engine scores |
| `queue.db` (SQLite) | outbound events while offline; local-brain turns to upload |
| `models/` | local LLM GGUF files, STT/TTS models, wake word models |
| `cache/` | phrase-bank audio (earcons, fillers), app index |
| keychain | ✅ service `SparkAI`: `brain-refresh-token`, `brain-device-id` (via keytar, main process only). The access token lives only in main-process memory |

## 8. Retention

| Data | Retention |
|---|---|
| messages, memories, artifacts | until the user deletes them or the account |
| usage_events | 13 months |
| incidents, audit_log | 90 days / 1 year |
| events (sync) | 7 days |
| otp_codes | deleted 24 h after expiry |
