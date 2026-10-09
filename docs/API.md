# API.md — Brain Contracts (v2)

Source of truth for the brain's HTTP API and the device gateway protocol. Change this file in
the same commit as the code. v1 contracts are in `legacy/API_v1.md`.

---

## 1. Conventions

- **Base URL:** `https://<brain-host>`. HTTP routes live under `/v2/...`; the device socket is
  Socket.IO namespace `/v2`.
- **Auth:** `Authorization: Bearer <access JWT>` (15 min). The desktop keeps the refresh token in
  the OS keychain. **No route or event accepts a `user_id` from the client.**
- **Envelope:**
  ```json
  { "ok": true,  "data": { } }
  { "ok": false, "error": { "code": "quota_exceeded", "message": "Human-readable, persona-voiced", "retry_after_s": 30 } }
  ```
- **Error codes:** `unauthorized` (401), `forbidden` (403), `not_found` (404), `invalid_input`
  (422), `rate_limited` (429), `quota_exceeded` (429), `provider_unavailable` (503), `internal` (500).
- **Pagination:** `?cursor=<opaque>&limit=<≤100>` → `{ items, next_cursor }`.
- **Idempotency:** mutating routes accept `Idempotency-Key`.
- **Rate limits:** per user and per IP via Redis token buckets; `429` carries `retry_after_s`.
- **Versioning:** breaking changes get a new prefix (`/v3`). Additive fields are allowed.

## 2. HTTP Routes

### 2.1 Auth & devices
| Method | Path | Body / Query | Notes |
|---|---|---|---|
| POST | `/v2/auth/otp/start` | `{ email }` | sends a 6-digit code; cooldown 60 s |
| POST | `/v2/auth/otp/verify` | `{ email, code, device }` | 5 attempts per code → tokens + `device_id` |
| GET | `/v2/auth/google/start` | `?device_name&platform&device_id&code_challenge&port` | opened in the system browser; OIDC sign-in (R4 adds Gmail/Calendar/Drive connect) |
| GET | `/v2/auth/google/callback` | provider redirect | state carries a server-stored nonce; redirects to the app's loopback listener |
| POST | `/v2/auth/google/exchange` | `{ code, code_verifier }` | one-time login code + PKCE verifier → tokens |
| POST | `/v2/auth/refresh` | `{ refresh_token }` | rotates; reuse → session revoked |
| POST | `/v2/auth/logout` | — | revokes this device's session |
| GET | `/v2/me` | — | profile + settings |
| GET | `/v2/devices` | — | ✅ `{ items: [{ id, name, kind, platform, app_version, parent_device_id, capabilities, engine_plan, is_default_for, last_seen_at, online, current }], next_cursor }` |
| PATCH | `/v2/devices/{id}` | `{ name?, is_default_for?: (phone\|laptop\|desktop\|tablet)[] }` | ✅ rename; default for "my phone"/"the laptop". A word moves off any other device that had it |
| DELETE | `/v2/devices/{id}` | — | ✅ revokes the device's sessions and forgets it; its socket drops within 30 s. Another user's id → `404` |

**Auth payloads (✅ built in R0).** Bodies reject unknown fields (`422 invalid_input`).
- `otp/start` → `{ sent: true, cooldown_s: 60 }`. Per-IP cap 10 / 10 min. The code lives 10 min and
  is stored only as a keyed hash. A send failure returns `503 provider_unavailable` and starts no cooldown.
- `otp/verify` body: `{ email, code: "6 digits", device: { name, kind?: desktop|mobile, platform?, app_version?, id? } }`.
  `device.id` re-uses a device you already own (its old sessions are revoked); otherwise a new device
  is registered. Wrong code → `401` with tries left; after 5 wrong tries the code is locked (`429`)
  even for the right code. Per-IP cap 30 / 10 min.
- Sign-in response (OTP, Google exchange): `{ access_token, access_expires_in: 900, refresh_token, device_id, user: { id, email, name } }`.
- `refresh` → `{ access_token, access_expires_in, refresh_token, device_id }`. The refresh token is
  `<session_id>.<secret>`; every refresh returns a new one. Presenting an old one revokes the whole
  session (`401`). Clients must refresh one call at a time.
- Every authenticated request also checks the session isn't revoked, so logout and reuse-revocation
  apply immediately, not after the 15-minute access token runs out.
- **Google (desktop, RFC 8252 loopback + PKCE):** the app listens on `127.0.0.1:<port>`, opens
  `google/start` with `code_challenge = base64url(sha256(code_verifier))` (S256), and the brain keeps
  state + nonce in Redis for 10 min. After Google, the brain checks the id_token (iss, aud, nonce, exp,
  `email_verified`) and redirects to `http://127.0.0.1:<port>/callback?code=<login code>` (60 s, single
  use) or `?error=cancelled|failed`. The app then calls `google/exchange`. A verified Google email
  that matches an existing account links to it. Unknown or expired state → a small HTML page in the browser.
- `GET /v2/me` → `{ user: { id, email, name, nickname, plan }, device_id, settings: {…§2.2} }`.

### 2.2 Settings, memory, usage
| Method | Path | Notes |
|---|---|---|
| GET / PATCH | `/v2/settings` | ✅ `{ language, auto_detect_language, voice, verbosity: brief\|normal\|detailed, address_as, permission_mode: default\|ask\|trust, allow_training_providers, models }`. PATCH sends only changed fields (`models` is read-only until R6); `voice`/`address_as` clear with `null`. `language` other than `en` → `422` "English is all I speak for now…". A real change pushes `settings.changed` to every device |
| GET | `/v2/memories` | list/search (`?q=`) |
| PATCH / DELETE | `/v2/memories/{id}` | edit / forget (removes the embedding) |
| GET | `/v2/usage` | today's usage per role/provider, quota left |
| GET / POST / DELETE | `/v2/keys` | user provider keys (free or BYOK); responses show provider + last 4 only |
| GET / POST / DELETE | `/v2/permissions/rules` | deny / ask / allow rules |
| POST | `/v2/account/export` | data export job |
| DELETE | `/v2/account` | delete account + data (confirmation token required) |

### 2.3 Threads, jobs, artifacts
| Method | Path | Notes |
|---|---|---|
| GET | `/v2/threads` / `/v2/threads/{id}/messages` | paginated history |
| GET | `/v2/jobs` / `/v2/jobs/{id}` | job state, todo, steps, usage |
| POST | `/v2/jobs/{id}/cancel` | same as a "stop" signal |
| GET | `/v2/artifacts/{id}` | metadata + signed download URL |
| POST | `/v2/uploads` | signed upload URL for large tool outputs/files |

### 2.4 Capabilities
| Method | Path | Notes |
|---|---|---|
| GET | `/v2/capabilities/tools` | tool catalog with risk + effective permission |
| GET / POST / DELETE | `/v2/skills` | list / import (zip or git URL) / remove |
| GET | `/v2/plugins/marketplaces` / `/v2/plugins` | browse; context cost shown per plugin |
| POST / DELETE | `/v2/plugins/{id}` | install (version-pinned) / uninstall |
| GET / POST / DELETE | `/v2/mcp/servers` | remote MCP servers; `POST` starts OAuth if needed |
| GET | `/v2/mcp/registry?q=` | search the MCP Registry |
| GET | `/v2/connectors` | Google / Slack / Notion status + scopes |
| GET | `/v2/connectors/{service}/connect` | starts OAuth (JIT connect cards use this) |
| DELETE | `/v2/connectors/{service}` | disconnect + revoke at the provider |

### 2.5 Voice proxy (platform keys stay server-side)
| Method | Path | Notes |
|---|---|---|
| POST | `/v2/proxy/tts` | `{ text, voice, tone? }` → streamed audio (Groq Orpheus); ≤ 200 chars per call, sentence-sized |
| POST | `/v2/proxy/stt` | audio chunk upload → transcript (Groq Whisper); used only when the engine plan picks cloud STT |

### 2.6 Engines & health
| Method | Path | Notes |
|---|---|---|
| GET | `/v2/engines/chains` | chain entries, enabled/paid, health, measured TTFT |
| GET | `/v2/incidents` | supervisor incidents for this user |
| GET | `/health` | liveness (no auth) |
| GET | `/ready` | DB, Redis, chain health (no auth, no details beyond up/down) |

## 3. Device Gateway Protocol (Socket.IO `/v2`)

Connect: `io(url + "/v2", { auth: { token: <access JWT>, device_id } })`. ✅ The auth object
must hold exactly those two fields; `device_id` must match the token, the session must be live, and a
refresh token is refused. Refusal → `connect_error` with `{ code: "unauthorized", message }`. The brain
re-checks the session every 30 s and drops the socket once it ends (logout, device removed, refresh
reuse). Presence lives in Redis while connected (`DATABASE.md` §6).

**Envelope:** `v` is `2`; `id` is unique per event (brain events use the `events.seq` sync id);
`ts` is epoch milliseconds; `trace_id` is optional. Device payloads reject unknown fields, so a
client `user_id` is refused. Acks use the HTTP envelope: `{ ok: true, data }` or
`{ ok: false, error: { code, message } }`. Each event carries
`{ v: 2, id, ts, trace_id }` plus the payload below. Events are acknowledged with Socket.IO acks
where noted.

### 3.1 Device → Brain
| Event | Payload | Notes |
|---|---|---|
| `device.hello` | `{ platform, app_version, capabilities[], tool_versions, hardware }` | ✅ on connect; ack `{ device_id, server_time }`; stored on the device row |
| `device.state` | `{ battery, power_mode, active_app, locale, mic, speaker }` | on change |
| `device.engine_plan` | `{ stt[], tts[], local_llm[], scores }` | after fitness runs (§18) |
| `wake.claim` | `{ score, loudness, foreground }` | wake-word arbitration (§26.2) |
| `signal.partial` | `{ signal_id, text }` | prefetch |
| `signal.final` | `{ signal_id, text, lang, confidence, source: voice\|text\|schedule }` | ack: `signal.ack` |
| `signal.handled_locally` | `{ signal_id, intent, slots, result }` | tier-0 reflex arc result (§27) |
| `signal.interrupt` | `{ signal_id? }` | barge-in / stop |
| `tool.progress` | `{ call_id, note, pct? }` | |
| `tool.result` | `{ call_id, ok, output \| error, artifacts[] }` | output validated against the tool's `output_schema` |
| `approval.response` | `{ approval_id, decision: allow\|deny\|always }` | |
| `ask.response` | `{ ask_id, answer }` | answer to `ask_user` |
| `engine.incident` | `{ role, engine, error, remedy }` | watchdog report (§19) |
| `sync.resume` | `{ last_event_id }` | replay missed events |

### 3.2 Brain → Device
| Event | Payload | Notes |
|---|---|---|
| `wake.grant` / `wake.yield` | `{ claim_id }` | yielding devices stop listening |
| `signal.ack` | `{ signal_id, tier, job_id? }` | within 300 ms |
| `reply.delta` | `{ signal_id, text, tone?, speak: bool, final: bool }` | sentence-level chunks; `tone` = persona tag |
| `reply.cue` | `{ kind: heard\|done\|error }` | earcons (§4.4) |
| `tool.call` | `{ call_id, job_id, tool, input, timeout_s, risk }` | |
| `tool.cancel` | `{ call_id }` | |
| `approval.request` | `{ approval_id, tool, summary, inputs_preview, risk, options }` | sent to all online devices; first answer wins |
| `ask.request` | `{ ask_id, question, options? }` | voice prompt + UI choice |
| `connect.request` | `{ service, scopes, reason, resume_job_id }` | just-in-time connect card (§23) |
| `job.update` | `{ job_id, status, todo[], step?, note?, eta_s? }` | |
| `artifact.new` | `{ artifact_id, kind, preview, thread_id }` | |
| `settings.changed` | `{ changed: {...} }` | ✅ pushed to every device of the user, including the one that changed it |
| `notice` | `{ text, from_device?, level }` | e.g. "Spark opened YouTube, asked from Laptop" |
| `fallback.notice` | `{ reason }` | brain degraded; the device switches to the local brain |

### 3.3 Tool call contract
- `input` validated against `input_schema` before sending; `output` validated against
  `output_schema` on return.
- Errors return `ok: false` with `{ code, message }` where `message` is actionable for the model
  ("App 'Spotify' isn't installed; installed media apps: VLC, Groove Music").
- `timeout_s` is enforced by both sides; the device sends `tool.progress` at least every 5 s for
  long calls.

## 4. Body ↔ Electron (local, stdio JSON-RPC)

`spark-body` and Electron main talk JSON-RPC 2.0 over stdio:
- Methods: `fitness.run`, `fitness.quick`, `engine.plan`, `tool.run`, `tts.speak`, `tts.stop`,
  `stt.start`, `stt.stop`, `local_brain.chat`, `models.search`, `models.download`.
- Notifications: `ear.wake`, `ear.partial`, `ear.final`, `mouth.started`, `mouth.done`,
  `watchdog.incident`, `download.progress`.
Electron main relays between this channel and the brain socket.
