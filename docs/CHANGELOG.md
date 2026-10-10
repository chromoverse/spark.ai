# CHANGELOG.md

Format: [Keep a Changelog](https://keepachangelog.com/). Entries before 2026-10-09 are unversioned milestones
backfilled from git history and grouped by theme.

---

## [Unreleased]

### Added
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
