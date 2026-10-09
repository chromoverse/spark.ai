# docs/ — Spark Documentation (v2)

**Spark** is a voice-first AI assistant: a cloud **Brain** (FastAPI) plus device **Bodies**
(desktop now, mobile later) that carry the sense organs (ear, mouth; eye later) and hands (local
tools). It's built to answer in under a second, act across devices, never fail silently, run on
free providers during the build, and talk like a person.

## Reading order

| # | Doc | What it's for |
|---|---|---|
| 1 | **`MEMORY.md`** | current state, decisions, risks. Read first, update after work |
| 2 | **`ARCHITECTURE.md`** | one-page system map |
| 3 | **`REDESIGN.md`** | the full v2 design and rationale (§ numbers are cited everywhere) |
| 4 | **`PHASES.md`** | roadmap R0–R7: what to build now and what not to |
| 5 | **`RULES.md`** | binding rules: isolation, latency, free-first, never silent, persona |
| 6 | **`TESTING.md`** | scenario matrix: every flow has a test |
| 7 | **`API.md`** · **`DATABASE.md`** · **`FOLDER_STRUCTURE.md`** | contracts, schema, layout (sources of truth) |
| 8 | **`PERSONA.md`** | how Spark talks: human, chill, honest |
| 9 | **`CODING_STANDARDS.md`** · **`DESIGN.md`** · **`ENVIRONMENT.md`** | how to write code, UI, setup |
| 10 | **`RESEARCH.md`** | Claude Code / Codex / MCP findings + free-provider reality (with sources) |
| 11 | **`PRD.md`** · **`PRIVACY_POLICY.md`** · **`PRODUCTION.md`** · **`CHANGELOG.md`** | product, privacy, deploy/ship, history |

`legacy/` holds the v1 docs (architecture, API, MongoDB schema, layout, packaging, latency prompt,
Groq note). Use them only when porting v1 code. Also `../graphify-out/GRAPH_REPORT.md` (code graph,
see the root `CLAUDE.md`).

## Golden rules

1. **Current phase only.** Port from v1, never extend it.
2. **≤ 1 s to first audio.** Measure every signal; skip the LLM only when sure.
3. **Never silent.** Every signal ends answered, done, cancelled, or explained.
4. **Free first.** Build stage = free providers only; paid comes later.
5. **Identity from the token only.** No client `user_id`, ever.
6. **Every scenario has a test** in the `TESTING.md` matrix.
7. **Talk like a person** (`PERSONA.md`).
8. **Docs move with code:** `API.md` / `DATABASE.md` / `MEMORY.md` in the same commit.

## Tech stack (v2, locked)

| Layer | Choice |
|---|---|
| Brain | Python 3.11, FastAPI, python-socketio (`/v2`), SQLAlchemy 2.0 async, Alembic, uv |
| Data | Postgres 16 + pgvector, Redis 7 |
| LLMs | free-first chains: Groq, NVIDIA free endpoints, Cloudflare Workers AI, Mistral credits, Gemini/Gemma (opt-in), OpenRouter free, local llama.cpp; Claude later (`PAID_PROVIDERS_ENABLED`) |
| Embeddings | local ONNX model (384-d) |
| Search / places | SearXNG (self-hosted) + DuckDuckGo; OpenStreetMap |
| Desktop | Electron + React 19 + TypeScript + Vite, Tailwind v4, shadcn/ui, lucide, Redux Toolkit, keytar |
| Body sidecar | Python: openWakeWord, VAD, per-device STT/TTS (Groq Orpheus, edge-tts, Pocket/Kokoro/Chatterbox, Piper), reflex arc, tool hands, ADB, CDP browser, sandbox, llama.cpp fallback |
| Deploy | VPS + Docker Compose (brain, Postgres, Redis, SearXNG, Caddy) |
