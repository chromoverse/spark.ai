# MEMORY.md — Running Project Memory

The project's working memory across sessions. Read it first; update it whenever meaningful work
happens.

---

## Current Progress

- **Direction:** v2: a cloud **Brain** + device **Bodies** (desktop now, mobile later). Full design
  in `REDESIGN.md`, one-page map in `ARCHITECTURE.md`, roadmap in `PHASES.md` (R0–R7).
- **Phase:** R0 Brain foundations **done** (2026-10-10) on branch `r0/brain-foundations`: every
  `PHASES.md` R0 box ticked. `brain/` (FastAPI + Socket.IO /v2, uv + `uv.lock`), `deploy/` compose
  stacks, 10-table migration, email OTP + Google (loopback + PKCE), rotating refresh tokens with
  reuse revoke, devices/presence/settings fan-out, test harness (FakeProvider/FakeDevice/FakeClock,
  X1–X3), Electron v2 sign-in + socket + status, whole-app Electron lint/typecheck green, GitHub
  Actions CI. Brain: 40 tests green, ruff + mypy strict clean. Owner's desktop smoke (§8a) passed
  2026-10-10: signed in, "Connected", brain stop → "Can't reach the brain", start → reconnected.
- **R0 pushed to `origin/main`** 2026-10-10 (fast-forward `ec23e38..ffd8142`; CI green on GitHub).
- **R1 in progress** on local branch `r1/voice-loop` (not pushed). Built and green (2026-10-10,
  overnight session): brain 85 tests (incl. 100-signal chaos), body 38 tests (Windows CI job added),
  Electron typecheck + lint (0 errors). What exists:
  - brain: free-first reflex chain (Groq ×2, Cloudflare, Gemini opt-in, Mistral; Claude Haiku 5.5
    paid/off) with 350 ms hedging, fallthrough, Redis health circuits, stall → `Restart`; the signal
    protocol (`signal.*`, `tool.result`, `engine.incident`, `device.engine_plan`, `reply.*`,
    `tool.call`); reflex with 7 quick device tools + `delegate` stub; tier-1 stop/language; persona
    block + banned-phrase lint + tone tags; supervisor watches, heard cue, 5 s deadline sweep,
    `incidents` table + `GET /v2/incidents`; voice proxy `/v2/proxy/tts|stt` (Groq Orpheus/Whisper).
  - body (`python -m spark_body`): tier-0 grammar (338-row eval, 0 false accepts), hands (volume,
    media keys, brightness, Start Menu apps), mouth (edge-tts, Orpheus via proxy, live switching,
    circuits, text-only degrade), fitness (hardware scan, benchmarks, plan, power re-probe, EWMA,
    SQLite history), STT plan (Groq Whisper via proxy), endpointer.
  - Electron: BodyBridge (spawn + restart), VoiceLoop relay (tier 0 first, tool calls, incidents,
    plans, trace), audio + earcons in one window, mic + VAD ear with barge-in, **Engines** page
    (plan, scores, reasons, Run benchmark, Try it with mic).
  - evals: `brain/evals` reflex (95) + persona (58) runners, latency report from logs.
- **R1 left** (see `PHASES.md` R1 notes): run the evals and latency bench with real keys and order
  the chain; local TTS engines (Kokoro/Piper/Pocket/Chatterbox) and on-device STT (need model
  downloads); wake word (`hey_spark.onnx`/`spark.onnx` aren't in the repo or on disk); speculative
  start in the live ear; RA3/RA4/PS3 need jobs/approvals (R2 machinery).
- **Owner to-do for R1:** put `GROQ_API_KEYS` (and any other free keys) in `deploy/.env`; accept
  Orpheus terms in the Groq console; `cd body && uv sync --extra tts --extra hands`; run the R1 smoke
  (`TESTING.md` §8b), then `cd brain && uv run python -m evals.run --suite reflex` and `--suite persona`.
  Decide: move RA3/RA4/PS3 to R2 (they need jobs), and whether to download local voice models now.
- **This laptop:** 8 cores, 7.4 GB RAM, AMD (no CUDA): local LLMs must be small (R5 Models page).
- **Deferred past R0:** per-user rate limits, `sync.resume`/X4, retention jobs, real Caddy config,
  Electron lint warnings (react-hooks exhaustive-deps).
- **Run locally:** `docker compose -f deploy/docker-compose.yml up -d` (brain on :8080; secrets in
  git-ignored `deploy/.env`). Tests: `docker compose -f deploy/docker-compose.test.yml up -d`, then
  `cd brain && uv run pytest`. Desktop: `cd electron && npm run dev`. uv lives in
  `%APPDATA%/Python/Python311/Scripts` (not on PATH).
- **Working tree:** the owner's uncommitted v1 edits (`server/*`, `README.md`, parts of
  `HomeLive.tsx` and `ActionExecutorService.ts`, `scripts/`, `*.env.example`) are theirs. Never stage them.
- **v1 state:** feature-rich prototype (`server/`, `voice_daemon/`, `llms/`, `electron/`). Runs in
  dev; no CI; 10 server unit tests (1 error). Reference material for porting only; never deployed.

## v2 Decisions (owner, 2026-10-09)

**Shape & stack**
- New brain core in this repo (`brain/`, `body/`); port tools; delete v1 phase by phase
- Postgres + pgvector + Redis
- **Development runs entirely on the laptop** (Docker Compose + local brain; free Cloudflare Tunnel
  when a public HTTPS URL is needed). VPS + Docker Compose only from R7 (beta/production), region by benchmark
- Sign-in: email OTP + Google; Windows first; English at launch (language switching designed in)

**Speed & reasoning**
- ≤ 1 s from end of speech to first audio; measured on every signal
- Four tiers: reflex arc (device, no LLM) → brain router (no LLM) → reflex LLM → agent (§27)
- Skip the LLM only when sure; UX never drops to save a call
- **Free first; build stage = free plans only** (`PAID_PROVIDERS_ENABLED=false`); Claude later
  (production or Claude startup credits)
- Free chains: Groq, NVIDIA free endpoints, Cloudflare Workers AI, Mistral credits, Gemini/Gemma
  (opt-in, trains on data), OpenRouter free, local llama.cpp. Reflex entries need p95 TTFT ≤ 400 ms;
  hedging at 350 ms

**Body**
- Every STT/TTS/local-LLM engine picked **per device by benchmark** (first run, every start, power
  or hardware change, continuously) (§18)
- Expressive TTS preferred: Groq Orpheus → edge-tts (from the device) → best local engine
- Cloud brain first; on failure Spark says so and uses a local model; the Models page downloads
  a hardware-appropriate model

**Reliability, capabilities, UX**
- Per-user **Supervisor** + device watchdog: never silent (§19)
- Tools/skills/plugins/MCP/hooks on open standards shared with Claude Code and Codex (§20)
- Cross-device: one account, wake-word arbitration, "on my phone/laptop", ADB now, mobile body later (§26)
- UI: Home, Activity, Capabilities, Engines, Settings + Ctrl+K; just-in-time connect cards (§23–§24)
- **Persona:** human, chill, sharp, honest; human wrap-ups (`PERSONA.md`)
- Permissions default: auto for safe, ask for risky; deny → ask → allow
- **Every scenario has an automated test** (`TESTING.md` §4)
- Keys: platform keys + quotas, optional BYOK; users' own free keys first; platform keys never leave the brain
- Billing: free beta with quotas, metering from day one, payments later

**Dependencies (R0)** — the stack table in `RULES.md` §2 covers the rest
- `uvicorn[standard]`: ASGI server for the brain
- `pydantic-settings`: typed config from env / `deploy/.env`
- `pyjwt`: access JWTs (HS256, secret from env)
- `pytest-asyncio`: async tests; `aiohttp` (dev): required by `socketio.AsyncClient` in FakeDevice
- `ruff`, `mypy`: lint/format and strict typing, enforced in CI
- Electron: no new packages (`keytar`, `socket.io-client` were already in v1)

**Dependencies (R1)**
- Brain: `anthropic` (official SDK, as REDESIGN §5.4 asks) for the paid Claude entries, off during the
  build. It runs on httpx2, so it keeps its own client with retries off. The OpenAI-compatible adapter
  uses the shared httpx client (no other provider SDKs).
- Body core: stdlib only (asyncio, sqlite3, ctypes). Optional extras, each admitted only when its
  engine passes fitness on the device: `tts` = `edge-tts` (free natural voices, device-side);
  `audio` = `sounddevice` + `numpy` (mic capture for the ear); `hands` = `pycaw` (exact volume on
  Windows) + `screen-brightness-control` (brightness beyond laptop panels). Without `hands`, volume
  falls back to volume keys and brightness to WMI.

**R1 implementation choices (2026-10-10, agent; owner can overrule)**
- Body ↔ Electron framing is NDJSON (one JSON-RPC object per line), not Content-Length frames.
- Audio is synthesized in the body and played in the renderer (Chromium decodes MP3/WAV; no Python
  audio decoder). Whole-sentence blobs for now; MediaSource streaming if first audio needs it.
- The R1 ear runs mic + Silero VAD in the renderer (`vad-web`, already a v1 dependency) with
  Chromium echo cancellation; STT engine choice stays in the body. A body-side ear (sounddevice +
  wake word) replaces it once the wake models exist.
- Live events (`reply.delta`, `reply.cue`, `tool.call`, `tool.cancel`) go only to the origin device
  and skip the sync log; the thread history holds the outcome. A turn is stored before its final
  marker, so a follow-up always sees it.
- If no TTS engine fits the 250 ms budget, the working ones stay in the plan (fastest first) instead
  of going mute; the heard cue covers the gap.
- Tier 0 is grammar-only (full match + every slot resolved + app in the installed index); the
  embedding classifier waits for its ONNX model.

## Completed Work

- **2026-10-09** — Full v2 doc set: REDESIGN, RESEARCH, PERSONA, ARCHITECTURE, API, DATABASE,
  FOLDER_STRUCTURE, PRD, RULES, CODING_STANDARDS, DESIGN, ENVIRONMENT, TESTING, PRIVACY_POLICY,
  PRODUCTION, PHASES, CHANGELOG. v1 docs moved to `docs/legacy/`.
- **2026-10-09** — Claude Opus 5.5 leads v1's streaming route (commit `ec23e38`); in v2 it's a paid
  chain entry, off during the build.
- Earlier history: `CHANGELOG.md`.

## v1 Security Issues (why v1 is never deployed; v2 must not repeat them)

1. Hardcoded JWT `SECRET_KEY` (`server/app/jwt/config.py`).
2. Unauthenticated routes trusting a client `user_id` (`legacy/API_v1.md`, ⚠️ rows): `POST /chat`
   runs tools for any user; `/auth/internal/token/{service}` returns live OAuth tokens;
   `/api/v1/auth/load_user` returns `api_keys`.
3. CORS `*` on HTTP and Socket.IO.
4. Plaintext `users.api_keys`, returned by `/get-me`.
5. OTP without attempt limits, stored plaintext; OAuth `state` without a nonce.
6. Socket accepts refresh tokens.
7. `electron/.env` and 77 `__pycache__` files tracked in git.

## Known v1 Bugs (v2 regression tests: D1, S5, T9)

- Calendar list said "no events" while events existed (even one just created).
- Summary contradicted tool output (invented events/emails).
- Gmail read got `step_1.maps_link` as a message id; literal user `me` → "No active gmail token for user me".
- Entity/artifact container had a close (×) button; the owner wants it removed (DESIGN.md: artifacts stay).
- v1 test `test_daemon_auth_accepts_service_token` errors (circular import).

## Open Questions / Risks

- **Free tiers are small and per account** (`RESEARCH.md` §5): Groq 1K req/day + 8K tokens/min;
  Orpheus 100 clips/day; Gemini Flash ~20/day; OpenRouter 50/day; Cerebras no longer free. Fine for
  the build; production needs users' own free keys + on-device compute + paid fallback. The 8K
  tokens/min limit forces lean agent prompts.
- **edge-tts** is unofficial and blocked from datacenter IPs → device only, with fallbacks.
- **Local TTS speed varies widely by CPU** (Kokoro < 1 s to ~3.5 s first audio) → the fitness check is mandatory.
- **Latency geography:** providers are far from Nepal/India; the R7 region benchmark picks the VPS region.
  Dev latency on the laptop won't match production exactly.
- **Google restricted scopes** (Gmail) need OAuth verification + CASA before public launch.
- **Free provider terms:** NVIDIA free endpoints are for prototyping only, and the Cohere trial is
  non-commercial. Re-check before production.
- Root working tree has deleted v1 planning docs (`BROWSER_AGENT_*.md`, `HACKATHON_PITCH.md`,
  `AGENTS.md`). The owner decides whether to commit those deletions.
- **Refresh rotation is strict:** any client must refresh single-flight or it revokes its own session.
- Sockets of a revoked session drop on the next heartbeat (≤ 30 s), not instantly.
- **Resend free tier** only delivers to the account owner's email until a domain is verified.
- The Google OAuth client must list `http://localhost:8080/v2/auth/google/callback` as a redirect URI.
- v1 desktop chat (via `server/`) is offline in the v2 app until R1/R2 wires chat to the brain.
- Rate limits are fixed-window per IP; per-user limits come later.
- **edge-tts misses the budget badly here:** measured on this laptop 2026-10-10 (5 runs × 2):
  first audio p50 ~740 ms, p95 ~1.6–1.8 s vs the 250 ms budget. With edge-tts alone the 1 s goal
  can't hold; Groq Orpheus (needs a key) or a local engine (Kokoro/Piper, needs a model download)
  has to lead the plan. Until then the plan runs "degraded" and the heard cue covers the gap.
- The tier-0 eval set was written alongside the grammar (0 false accepts is partly self-graded);
  add real transcripts from use before trusting the < 0.5% number.
- In-process maps (`Voice.calls`, `prefetch`, supervisor watches) assume the device's socket lives
  on the brain process that got the signal; cross-device tool calls (R2) need Redis pub/sub.

## Context for Future Sessions

- Start from `docs/README.md` reading order. Section numbers like §26 refer to `REDESIGN.md`.
- v1 maps for porting: `legacy/ARCHITECTURE_v1.md`, `legacy/API_v1.md`, `legacy/DATABASE_v1.md`,
  plus the code graph (`graphify-out/`).
- v1 tests: `server/.venv/Scripts/python.exe -m unittest discover -s tests` (pytest isn't installed there).

## Bugs & Fixes Log

| Date | Bug | Fix |
|---|---|---|
| 2026-10-09 | Socket refusals lost the `unauthorized` code (builtin `ConnectionRefusedError`) | `socketio.exceptions.ConnectionRefusedError("unauthorized", {...})`; wire shape asserted |
| 2026-10-09 | X1 sweep passed vacuously: FastAPI 0.143 `app.routes` holds lazy `_IncludedRouter` | Route table from OpenAPI + non-empty guard; mutation-tested |
| 2026-10-09 | v1 `waitForSpeechComplete` always waited 30 s (stale `isSpeaking` closure) | Polls a ref |
| 2026-10-10 | Desktop main process died at start (`0x80000003`): on Electron 39.2 touching Node's lazy WebSocket (`globalThis.WebSocket` via socket.io-client, `import http`) before `ready` crashes | `main.ts` imports only `electron` statically, app modules after `whenReady()`; ESLint rule blocks static imports there |
| 2026-10-10 | A quick follow-up didn't see the previous turn (stored after the final marker) | Store the turn, then send the final marker |
| 2026-10-10 | A body that started after the socket connected waited 10 min for its brain link | Relink on every body `ready` |
| 2026-10-10 | Vite `EACCES` on :5123 after Docker started | Windows dynamic port range started at 1024, so Hyper-V reserved 5041–5140; reset to 49152+ (`netsh int ipv4/ipv6 set dynamic tcp start=49152 num=16384`) + restart `winnat` |
