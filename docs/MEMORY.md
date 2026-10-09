# MEMORY.md — Running Project Memory

The project's working memory across sessions. Read it first; update it whenever meaningful work
happens.

---

## Current Progress

- **Direction:** v2: a cloud **Brain** + device **Bodies** (desktop now, mobile later). Full design
  in `REDESIGN.md`, one-page map in `ARCHITECTURE.md`, roadmap in `PHASES.md` (R0–R7).
- **Phase:** R0, Brain foundations. Not started; waiting for the owner's final review of the docs.
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

## Context for Future Sessions

- Start from `docs/README.md` reading order. Section numbers like §26 refer to `REDESIGN.md`.
- v1 maps for porting: `legacy/ARCHITECTURE_v1.md`, `legacy/API_v1.md`, `legacy/DATABASE_v1.md`,
  plus the code graph (`graphify-out/`).
- v1 tests: `server/.venv/Scripts/python.exe -m unittest discover -s tests` (pytest isn't installed there).

## Bugs & Fixes Log

| Date | Bug | Fix |
|---|---|---|
| — | — | — |
