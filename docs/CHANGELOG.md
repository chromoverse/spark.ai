# CHANGELOG.md

Format: [Keep a Changelog](https://keepachangelog.com/). Entries before 2026-10-09 are unversioned milestones
backfilled from git history and grouped by theme.

---

## [Unreleased]

### Added
- 2026-10-12 — **R4 web tools** (branch `r4/integrations`): `web_search` (self-hosted SearXNG,
  news + time range), `web_fetch` (own fetcher: private addresses refused at every redirect hop,
  only the passages about the question, ranked by the local embedder), `weather` (Open-Meteo, no
  key). The safety reviewer and sub-agents now run on gpt-oss-120b first (extraction stays on 20b).
- 2026-10-11 — **R3 Memory & learning** (branch `r3/memory`): `memories` table (halfvec + HNSW,
  generated tsvector + GIN), a local multilingual embedder in the brain (e5-small int8 ONNX,
  downloaded on first start), hybrid search fused by reciprocal rank (p95 18–22 ms at 10k
  memories per user), background extraction of durable first-person facts on a free `memory`
  chain (corrections replace, the same words merge, close vectors never do, small unused memories lapse), the profile in
  every reflex prompt and found memories in the volatile note (prefetched on partials),
  `remember` / `recall` / `forget` (agent saves wait for the user's OK), Settings → Memory,
  prompt-cache hit rate per role, memory evals (extraction 32/32 on gpt-oss-20b)
- 2026-10-11 — **R2 Agent loop + desktop hands** (branch `r2/agent-loop`): brain agent loop on a
  free-first agent chain (parallel tool calls, schema checks, malformed → next entry, repeat guard,
  budgets, grounding check, ≤ 3-sentence wrap-ups with the rest as an artifact); jobs (persisted
  steps, cancel / steer / status, ETA notes) synced to every device; permission engine (modes,
  deny → ask → allow rules with patterns, "always allow", first-answer-wins approvals, auto-reviewer
  for medium-risk writes), hooks (redaction, audit); `todo_write`, `ask_user`, `task`, plan
  approval, `tool_search`; 25 desktop hands in the body (files with Recycle Bin deletes and
  organize/restore, shell, clipboard, screenshot, keyboard/mouse, apps/processes, system);
  cross-device control (target resolution, queued runs for offline devices, wake-word
  arbitration, handoffs); artifacts with signed downloads; agent eval (30 tasks); desktop UI
  redone: the voice overlay as a notch at the top of the screen and a five-destination main window
  (Home, Activity, Capabilities, Engines, Settings) with Ctrl+K
- 2026-10-10 — **R1 Voice loop** (branch `r1/voice-loop`): `body/` sidecar (stdio JSON-RPC) with
  tier-0 reflex arc, hands, mouth (Groq Orpheus via the brain, edge-tts, Piper/Kokoro on device),
  ear (wake word "Hey Spark" by keyword spotting, Moonshine / Groq Whisper STT), per-device
  fitness and model downloads; brain free-first reflex chain with hedging, circuits, supervisor
  (never silent, incidents), persona lint, tier-1 router, signal protocol and traces; Electron
  voice loop, mic ear with wake gate, bounded follow-ups, speculative start, Engines page; evals
  (reflex, persona, latency with a scripted ear). Low-spec laptop: first audio p50 1.29 s, p95
  1.62 s over 50 scripted utterances
- 2026-10-09 — **R0 Brain foundations** (branch `r0/brain-foundations`): `brain/` FastAPI +
  Socket.IO `/v2` (uv-locked), `deploy/` local dev and test compose stacks (Postgres 16 + pgvector,
  Redis, SearXNG; Caddy stub), first Alembic migration (10 tables), email OTP (hashed, 5 tries,
  cooldown, Resend) + Google sign-in (loopback + PKCE), 15-min access JWTs + rotating per-device
  refresh tokens with reuse → revoke, device sockets with `device.hello`, Redis presence and
  `settings.changed` fan-out, test harness (FakeProvider, FakeDevice, FakeClock; X1–X3 + R0
  acceptance), Electron v2 sign-in (keychain refresh token, main-process socket, status pill),
  GitHub Actions CI (brain ruff/mypy/pytest, Electron lint/typecheck)
- 2026-10-09 — **v2 documentation**: `REDESIGN.md` (cloud brain + device bodies, reflex arc, free-first
  chains, per-device engine fitness, supervisor, capabilities platform, cross-device flows),
  `RESEARCH.md` (Claude Code, Codex, MCP, free providers), `PERSONA.md` (how Spark talks), and v2
  rewrites of ARCHITECTURE, API, DATABASE, FOLDER_STRUCTURE, PRD, RULES, CODING_STANDARDS, DESIGN,
  ENVIRONMENT, TESTING (scenario matrix), PRIVACY_POLICY, PRODUCTION, PHASES (R0–R7). v1 docs
  moved to `docs/legacy/`.
- 2026-10-09 — `docs/` documentation set (README, PRD, ARCHITECTURE, PHASES, RULES, MEMORY, API,
  DATABASE, DESIGN, FOLDER_STRUCTURE, CODING_STANDARDS, ENVIRONMENT, TESTING, PRIVACY_POLICY,
  CHANGELOG)
- 2026-10-09 — Claude Opus 5.5 (`AnthropicClient`) leads the streaming route for PQH/SQH/chat;
  skipped when no `ANTHROPIC_API_KEY` is set

### Removed
- 2026-10-11 — v1 desktop code the v2 UI replaced: `electron/action_executor/` and
  `electron/python-service/`, the executor IPC (`executeTasks`), the v1 server socket and token
  store, the v1 pages and components, device-usage polling, and 13 npm packages nothing imported

### Fixed
- 2026-10-09 — Whole-app Electron lint is green (v1 renderer + main), so CI can gate on it

---

## 2026-05-28 — Browser agent & web research

### Added
- Browser agent over CDP with persistent sessions and tab reuse
- Commerce automation, receipt watching, live checkout progress, disconnect handling
- Booking adapter with hotel target detection; Spotify integration; human-in-the-loop signals
- Entity-centric web research: cross-provider intent/amenity registry, OpenStreetMap geo-resolver
  with circuit breaker and caching, parallel search, location injection
- Live thread management for real-time task execution
- Inline entity action progress in the UI

## 2026-05-19 → 2026-05-25 — Agent runtime, plugins, UI overhaul

### Added
- Plugin-based tool runtime (`server/plugins/installed/*`), category-based tool routing,
  LLM-assisted error recovery
- Job coordination; job-based isolation for task and tool outputs
- Clarification service, tool caching, memory module, background learning
- Intelligent provider routing and unified API key management; Cohere provider
- Real-time activity logs and Spark self-control tools
- Google Drive tools; expanded web research entities
- New design system (`--sp-*`), connector management, onboarding overhaul, quota arc with
  provider breakdown, TTS summary in UI, confidential action modal

### Changed
- Agent runtime and tool execution architecture overhaul
- Local LLM: optimized inference engine, hardware-aware model selection

### Fixed
- Quota endpoint path (`/api/v1` prefix stripped)

## 2026-03-05 → 2026-04-05 — Voice, tools, integrations

### Added
- Gmail API tools; music playback/pause/resume; microphone control; artifact management
- `SystemSearcher` for system-wide search; WebResearchTool `max_results`
- TTS interrupt management; speculative pre-fetch of user context during speech
- Voice daemon unit tests; storage migration, tool catalog, and registry tests
- Runtime dependency bootstrap, device profile detection; Cloudflare KV cache support
- Failure message handling; WhatsApp automation and audio call automation
- Production/distribution blueprint (now `docs/legacy/PRODUCTION_v1.md`)

### Changed
- Tools plugin moved inside the server; cache management refactor; chat context handling

## 2026-02-02 — Initial

### Added
- Initial FastAPI server, Electron app, and base files

---

## Template for Phase Completions

```
## [Phase X] - YYYY-MM-DD
### Added
### Changed
### Fixed
### Security
### Tested
### Notes
```
