# ARCHITECTURE.md — Spark v2 System Map

The one-page map. Rationale and full detail are in `REDESIGN.md` (section numbers below). Contracts
are in `API.md`, data in `DATABASE.md`, layout in `FOLDER_STRUCTURE.md`. v1 docs are in `legacy/`.

## 1. Components

| Component | Runs | Role |
|---|---|---|
| **Brain** (`brain/`) | cloud VPS, Docker | auth, signal routing, reflex + agent reasoning, orchestration, memory, permissions, supervisor, integrations, sync, usage |
| **Postgres + pgvector** | VPS | users, devices, threads, jobs, memories (vectors), skills/plugins, usage, incidents |
| **Redis** | VPS | presence, hot cache, rate limits, provider health, pub/sub |
| **SearXNG** | VPS | free self-hosted web search |
| **Caddy** | VPS | HTTPS, reverse proxy |
| **Desktop body** (`electron/` + `body/`) | user's PC | UI, keychain tokens, brain socket; Python sidecar for ear (wake word, VAD, STT), mouth (TTS), hands (tools, ADB, browser), fitness benchmarks, watchdog, local brain fallback |
| **Mobile body** | later | same protocol, its own ear/mouth/hands |

```
 Desktop body ── Socket.IO /v2 (text, tool calls, events) ──► Brain ──► LLM providers (free chains)
   ear/mouth/hands on device                                 │       ──► Google / Slack / Notion / MCP
   reflex arc (tier 0, no LLM)                               │       ──► SearXNG / OSM
   local LLM fallback                                        └─► Postgres+pgvector, Redis
 Phone ── ADB via laptop (now) | mobile body (later)
```

## 2. How a signal is handled (§4, §26, §27)

| Tier | Where | Handles | LLM |
|---|---|---|---|
| 0 Reflex arc | device | simple, unambiguous commands (media, volume, apps, timers…) | none |
| 1 Brain router | brain | cross-device routing of simple intents, job status, approvals, cached results | none |
| 2 Reflex | brain | conversation and actions needing understanding; speaks first, acts in parallel | fast free model |
| 3 Agent | brain | multi-step tools, research, analysis; streamed progress + human wrap-up | stronger free model |

**Latency budget:** end of speech → first audio ≤ 1 s (§4.2). Partial transcripts prefetch
context, a speculative start on the endpoint candidate, hedged LLM requests at 350 ms, and
per-device TTS selection keep it there.

## 3. Reasoning (§5)

- Provider chains per role. **Build stage: free only** (Groq, NVIDIA free endpoints, Cloudflare
  Workers AI, Mistral credits, Gemini/Gemma opt-in, OpenRouter free, local llama.cpp). Claude
  (Haiku → Sonnet → Opus) switches on later via `PAID_PROVIDERS_ENABLED`.
- Reflex entries must measure p95 time-to-first-token ≤ 400 ms; the agent chain is ordered by
  reasoning quality then headroom.
- Two adapters: OpenAI-compatible (all free providers + local) and Anthropic.
- Agent loop = Claude Code style: native tool calls, parallel execution, deny → ask → allow
  permissions, sub-agents, todo list, plan approval, ask_user.

## 4. Body intelligence (§18, §19)

- **Fitness:** every STT/TTS/local-LLM engine is benchmarked on the device (first run, every start,
  on power or hardware change, continuously from real calls). Only engines that fit the budget are
  used, ranked by expressiveness (TTS) or accuracy (STT).
- **Supervisor (brain) + watchdog (device):** deadlines on every stage, hedging, switching,
  bridging cues, re-routing, re-planning, asking, or explaining. Every signal ends answered,
  done, cancelled, or explained. Never silent.

## 5. Capabilities (§7, §20–§23)

Typed tools (risk levels, schemas, MCP-compatible annotations), Agent Skills (`SKILL.md`, importable
from Claude Code / Codex), plugins with marketplaces, MCP (remote in the brain, local stdio via the
body), hooks/automations, workflow mode (sandboxed code calling tools), the research pipeline with
citations, typed artifacts, and just-in-time account connect cards.

## 6. Memory (§8)

Thread history (Postgres + Redis hot cache) → background extraction of facts → hybrid retrieval
(pgvector HNSW + full-text) with local embeddings → a short profile always in the prompt.
Governance: expiry, confirmation for memories from external content, user-visible Memory page.

## 7. Cross-device (§26)

One account → many devices. Wake-word arbitration, target resolution (explicit, implicit, capability
fallback, offline queue), handoffs, a shared thread. Phone control over ADB now; native mobile body later.

## 8. Persona (`PERSONA.md`)

Human, chill, sharp, honest. Speak first, act in parallel, wrap up like a person. Tone tags drive
expressive voices.

## 9. Security & privacy (§12, `PRIVACY_POLICY.md`)

Identity only from verified tokens; per-device rotating refresh tokens; encrypted BYOK and OAuth
tokens; deny → ask → allow permissions with approvals for risky actions; audio stays on the device
unless the device's engine plan falls back to cloud STT; free providers that train on data are opt-in.

## 10. Deployment (`PRODUCTION.md`)

Brain: Docker Compose on a VPS (brain, Postgres, Redis, SearXNG, Caddy), backups, monitoring.
Desktop: electron-builder NSIS installer with the embedded-Python body sidecar, auto-update, code signing.
