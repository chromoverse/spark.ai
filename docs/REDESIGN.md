# REDESIGN.md — Spark v2: Brain, Sense Organs, Body

**Status:** design, 2026-10-09. Decisions confirmed by the owner; final review pending before R0.
**Source:** owner's notes (3 pages, 2026-10-09) + decisions in §1.
**Companion docs:** `ARCHITECTURE.md` (one-page map), `API.md` (contracts), `DATABASE.md` (schema),
`FOLDER_STRUCTURE.md` (layout), `PERSONA.md` (voice), `TESTING.md` (scenario matrix). v1 docs: `legacy/`.

---

## 1. Decisions (locked 2026-10-09)

| Topic | Decision |
|---|---|
| Shape | **Brain** = one cloud FastAPI service. **Sense organs** (ear, mouth; eye later; feel much later) and **Body** (UI, local tools) live in device apps. Desktop now, mobile later, synced per user |
| Rewrite | New brain core written fresh in this repo; existing tools ported plugin by plugin; legacy deleted as it's replaced |
| **Cost policy** | **Free first, paid last.** For every role (reflex, agent, STT, TTS, embeddings, web search), free options lead the chain when they pass the quality bar for that role (§5.5). **Build stage: free plans only** (`PAID_PROVIDERS_ENABLED=false`); paid entries switch on for production or when Claude startup credits arrive |
| Reasoning | **Reflex + agent.** Fast model answers and starts speaking in < 1 s; a stronger model runs the tool-calling agent loop. Both are provider chains, free first (§5.3) |
| Offline | Cloud brain is always first. On cloud failure Spark says so explicitly and falls back to a **local model on the desktop**. Onboarding explains this and opens the **Models** page to download a model sized for the machine, auto-configured after download |
| Keys | Platform keys by default with per-user quotas; optional BYOK lifts limits. Users can add their own **free** provider keys (Groq, Gemini, OpenRouter), which are tried before platform keys |
| Billing | Free beta with quotas, usage metered from day one; payments later |
| Database | **Postgres + pgvector** (durable data + vectors) and **Redis** (presence, cache, rate limits, pub/sub) |
| Voice | **Engines picked per device by benchmark** (§18): every STT/TTS candidate is measured on the user's machine and only those that meet the latency budget are used. TTS prefers expressive: Groq Orpheus (vocal directions) → edge-tts (run from the device) → best local engine (Pocket TTS / Kokoro / Chatterbox-Nano / Piper). STT: on-device model → Groq Whisper free |
| Language | English at launch. `language` + auto-detect + "switch language" designed in now; Hindi/Nepali later = config + models |
| Hosting | **Development: everything on the laptop** (Docker Compose + local brain; a free Cloudflare Tunnel when a public HTTPS URL is needed). **Beta/production (R7):** VPS + Docker Compose (brain, Postgres, Redis, SearXNG, Caddy) in the region chosen by measured latency (§4.3) |
| Sign-in | Email OTP (rate-limited, hashed) + Sign in with Google |
| Permissions | Default mode: **auto for safe, ask for risky**; user can switch modes and "always allow" per tool |
| Desktop OS | Windows first; tool layer written cross-platform |

## 2. Principles

1. **The brain decides, the body acts.** All auth, reasoning, planning, memory, and orchestration
   happen in the brain. Devices sense, render, and execute tools they're asked to run.
2. **Never drop a true signal.** Every signal that passes device-side filtering gets an answer,
   an acknowledgement, or an explicit failure. Nothing fails silently.
3. **Speak first, then work.** The first audible response is never blocked by tool work.
4. **One agent loop, native tool calling** (Claude Code model), not prompt-parsed JSON plans.
5. **Every action is a typed tool** with a risk level the permission engine understands.
6. **Measure latency on every signal.** If it isn't measured, it isn't fast.
7. **Free first.** Prefer free models and services when they meet the bar; pay only as a last resort.

## 3. System Overview

```
                ┌─────────────────────────── BRAIN (cloud, FastAPI) ───────────────────────────┐
                │  Gateway (Socket.IO /v2)  ─  Auth  ─  Signal router  ─  Job runtime            │
                │       │                                   │                                    │
                │   Reflex (free chain) ── delegate ──► Agent loop (free chain; Claude later)     │
                │       │                                   │   ├ sub-agents (free chain)         │
                │       └── quick tools                     │   ├ tool router → brain tools       │
                │                                           │   │              → device tools ────┼──┐
                │  Memory (extract → pgvector + FTS)  ─  Permissions  ─  Usage/quotas  ─ Scheduler│  │
                │  Supervisor: per-user watcher of every signal, job, engine (§19)                │  │
                │  Integrations: Google · Slack · Notion · MCP · web search/fetch                 │  │
                │  Postgres + pgvector          Redis (presence, cache, rate limit, pub/sub)       │  │
                └───────────────▲──────────────────────────────────────────────────────────────┘  │
                     text signals│ reply deltas, tool calls, approvals, job events                │
                ┌───────────────┴──────────── DESKTOP (Electron) ──────────────────────────────┐ │
                │  Main: brain socket, keychain tokens, windows/tray, IPC                       │◄┘
                │  Renderer (Body/UI): conversation, jobs, approvals, settings, Models page     │
                │  spark-body (Python sidecar, stdio JSON-RPC):                                  │
                │    ear: wake word → VAD → STT (per-device)  mouth: TTS (per-device) + barge-in │
                │    hands: system, files, shell, apps, input, screen, browser (CDP), ADB       │
                │    local brain: llama.cpp + small tool loop (cloud-failure fallback)          │
                │    fitness: per-device engine benchmarks · watchdog (mirrors brain supervisor)│
                └───────────────────────────────────────────────────────────────────────────────┘
                MOBILE (later): same gateway protocol, its own ear/mouth/hands
```

## 4. Signal Lifecycle & Latency

### 4.1 Path of one spoken signal

1. **Ear (device):** wake word (sherpa-onnx open-vocabulary keyword spotting: no custom model to train) or push-to-talk → VAD → streaming STT emits partial
   transcripts locally.
2. **Filter (device):** drop non-speech, low-confidence, and self-echo (Spark's own TTS). Partial
   transcripts go to the brain as `signal.partial` so it can **prefetch** memory and context.
3. **Endpoint (device):** end of utterance → `signal.final { text, lang, confidence, device_id }`.
3a. **Reflex arc (device):** simple, unambiguous commands are executed right here with no LLM
   (§27); the brain is told afterwards.
4. **Router (brain):** attach to the user's active thread; decide interrupt / follow-up / new job (§6.4).
5. **Reflex (brain):** one streamed call to the first available model in the reflex chain. Output text streams to the device as
   `reply.delta` and is spoken sentence by sentence.
6. Reflex either (a) answers, (b) calls a **quick tool** after saying what it's doing ("Opening
   Spotify."), or (c) calls `delegate(task, ack)`: the ack is spoken immediately and the
   **agent loop** takes over (§5.2).
7. **Mouth (device):** the device's selected TTS engine (§18) synthesizes each sentence as it
   arrives; barge-in stops playback locally.

### 4.2 Latency budget: end of speech → first audio ≤ 1000 ms

| Stage | Budget | How |
|---|---|---|
| Endpointing | 200 ms | VAD silence threshold; **speculative start**: fire reflex at ~200 ms silence, cancel if speech resumes |
| Device → brain | 30–80 ms | persistent WebSocket, text only (no audio upload) |
| Context assembly | 20 ms | prefetched during speech: Redis hot cache (profile, recent turns), pgvector lookup already done |
| Brain → LLM provider → first token | 350 ms | Groq free tier (fast time-to-first-token); later Haiku 5.5 with thinking off and effort `low`; warm HTTP/2 connection |
| First sentence complete | 100 ms | stream; cut at first clause boundary (port v1 `stream_service` splitter) |
| Brain → device | 30–80 ms | |
| TTS first audio | 150–250 ms | engine chosen by the device benchmark (§18); sentence-level streaming |
| **Total** | **~880–1080 ms** | measured per signal (§13); the supervisor hedges when a stage runs late (§19) |

Agent work (multi-step tools) is not bounded by 1 s. It streams progress: spoken updates,
the job panel, and a final spoken summary.

### 4.3 Region

The LLM provider round trip dominates. Device↔brain carries only text. During development the
brain runs on the laptop, so there is no region to pick. Before beta (R7), candidate VPS regions
(Mumbai/Singapore vs US-East) are rented for a few hours and benchmarked for users in Nepal/India,
and the lower **total** wins. Keep one region until measurements say otherwise.

### 4.4 Speak, act, confirm (parallel action + done acknowledgement)

- **Heard-you cue:** at endpoint the device plays a short earcon from local cache (~0 ms) whenever
  the supervisor predicts first audio will miss 1 s. The user always knows Spark heard them.
- **Act in parallel with speech:** the reflex speaks its intent ("Opening Spotify and playing
  lo-fi.") while the tool call is already running. Speech never waits for the action, and the
  action never waits for speech to finish.
- **Done acknowledgement**, depending on the outcome:
  | Outcome | Acknowledgement |
  |---|---|
  | Quick action succeeded within 1.5 s | soft "done" chime + check mark in the UI; no extra speech |
  | Quick action succeeded after 1.5 s | short spoken "Done." (or the result if one was asked for) |
  | Action failed | spoken reason + next step ("Spotify isn't installed. Want me to open the web player?") |
  | Agent job | progress notes at milestones, then a spoken summary built only from tool outputs |
- A verbosity setting (quiet / normal / chatty) adjusts the thresholds.

## 5. The Brain's Mind

Each role is a **provider chain**: an ordered list of models. A call goes to the first entry that
is enabled, available, under quota, and healthy (§19 tracks health).

**Build stage (now): free plans only.** `PAID_PROVIDERS_ENABLED=false` removes every paid entry
from every chain. During the build the main user is the developer, so one account's free limits
are enough. Paid entries (Claude) switch on later, for production or when Claude startup-program
credits arrive. They stay in the design so turning them on is config, not code.

### 5.1 Reflex — fast spoken answer + quick tools

- **Most signals never reach this LLM:** the reflex arc (§27) handles simple commands without
  one. The reflex LLM is only for what needs language understanding.
- **Free chain (build), latency-qualified:** a model is admitted only if its measured p95
  time-to-first-token from the brain is ≤ 400 ms. Candidates: Groq `openai/gpt-oss-20b` →
  Groq `openai/gpt-oss-120b` → local model on the device (fit GPU machines, §18) → Cloudflare
  Workers AI (Llama 3.3 70B / gpt-oss-20b) → Gemini Flash-Lite (if allowed) → Mistral Small 4.
- **Hedging keeps < 1 s:** if the first provider hasn't produced a token by 350 ms, the same
  request goes to the next qualified entry in parallel and the first stream to answer wins.
- **Paid (later):** Claude Haiku 5.5 (`claude-haiku-5-5`, thinking off, effort `low`), the
  cheapest capable paid model.
- Streamed. Prompt order for caching: tools (deterministic order) → static system prompt →
  user profile summary → recent turns → signal. Per-turn context goes last.
- Tools: about 15 **quick tools** (volume, media, open/close app, time/date, timer, brightness,
  clipboard, lock screen, `set_language`, `remember`) + `delegate`.
- Prompt rule: say a short spoken phrase before any tool call; delegate anything multi-step,
  research-heavy, or risky.

### 5.2 Agent loop — multi-step tool work

Claude Code's loop: the model calls tools, the harness runs them, results go back, and it repeats
until it's done. The loop is provider-neutral. Messages are stored as Anthropic-style content
blocks, and the OpenAI-compatible adapter converts them for other providers.

- **Free chain (build), ordered by reasoning quality then headroom:** Groq `openai/gpt-oss-120b` →
  NVIDIA free endpoints (DeepSeek V4, Kimi K3, Nemotron 3 Super) → Cloudflare Workers AI
  (gpt-oss-120b, Kimi K2.5) → Mistral Medium/Large (free credits, training opt-out set) → Gemini
  Flash (if allowed) → OpenRouter `:free`. Combined, these give hundreds to thousands of agent
  turns a day during the build. The R1/R2 evals decide the final order.
- **Paid (later), escalating by cost:** Claude Haiku 5.5 → Claude Sonnet 5.5 → Claude Opus 5.5.

```
messages = thread_context + delegated_task
provider = chain.first_available()
loop:
    stream = provider.stream(tools, system, messages, effort=job.effort)
    forward text + progress notes → job events (UI) / spoken updates
    response = stream.final()
    if response.stop in ("end_turn", "refusal", "max_tokens"): finish
    tool_uses = response.tool_uses
    validate each input against its schema
    decisions = permission_engine.check(tool_uses)        # deny → ask → allow
    results = await gather(run(tu) for tu in tool_uses)    # parallel; per-tool timeout
    messages += [assistant(response.content), user(all tool_results)]  # one message, all results
    if supervisor.escalate(job): provider = chain.next()   # §19
```

- **Escalation inside a job:** 2 malformed tool calls in a row, a step budget hit with no progress,
  a rate limit or outage, or the user saying "that's wrong, try again". The job continues on the
  next chain entry with the same history.
- **Small-context discipline for free models:** Groq's free tier allows 8K tokens/min, so agent
  prompts must stay lean (§21): a compact system prompt, a pre-selected tool subset, concise tool
  outputs, and sub-agents for anything heavy.
- **When Claude is on:** adaptive thinking with `display: "updates"` for progress notes, explicit
  `effort` (`medium` default), refusal fallbacks (`fallbacks: "default"`), `tool_choice: auto` +
  `strict: true`, eager input streaming, tool search for deferred tools, compaction.
- **Sub-agents:** `task(description)` runs an isolated loop on the sub-agent chain with a narrow
  tool set and returns only its final result.
- **Planning:** `todo_write` checklist in the job panel; plan approval for risky jobs.
- **Clarification:** `ask_user(question, options)` as a voice prompt + UI choice; blocks the job.

### 5.3 Chains at a glance

| Role | Free (build stage, on now) | Paid (production / credits, off now) |
|---|---|---|
| Reflex (after the reflex arc, §27) | Groq gpt-oss-20b/120b → local model (fit devices) → Cloudflare → Gemini Flash-Lite (opt-in) → Mistral Small; p95 TTFT ≤ 400 ms or excluded; hedged at 350 ms | Claude Haiku 5.5 |
| Agent | Groq gpt-oss-120b → NVIDIA free (DeepSeek V4 / Kimi K3 / Nemotron) → Cloudflare → Mistral (credits) → Gemini (opt-in) → OpenRouter free | Haiku 5.5 → Sonnet 5.5 → Opus 5.5 |
| Sub-agents, memory extraction | Groq gpt-oss-20b → Cloudflare → NVIDIA free → OpenRouter free | Claude Haiku 5.5 |
| Vision (images, video frames) | Gemini Flash-Lite free (opt-in) → local vision model (fit devices) | Claude Haiku 5.5 |
| Embeddings | local ONNX model in the brain | — |
| STT | per device (§18): on-device model → Groq Whisper free | Deepgram |
| TTS | per device (§18): Groq Orpheus (expressive, while free quota lasts) → edge-tts from the device → best local engine | Groq Orpheus paid, Cartesia / ElevenLabs |
| Web search / fetch | SearXNG (self-hosted) + DuckDuckGo; own fetcher | Anthropic web tools |
| Places / entities | OpenStreetMap (Nominatim / Overpass) | Google Places, Foursquare |
| Offline | local GGUF via llama.cpp on the device | — |

Cerebras is not in the free chains: it ended its recurring free tier in mid-2026 (`RESEARCH.md` §5).
Chains are config (`brain/app/llm/chains.py`).

### 5.4 Providers

Two adapters instead of v1's eight clients:
- **OpenAI-compatible:** Groq, NVIDIA, Cloudflare Workers AI, Mistral, Gemini (OpenAI-compatible
  endpoint), OpenRouter, and the device's local llama.cpp server. Tool calls are normalized to the internal content-block format.
- **Anthropic** (official SDK): paid entries, off during the build.

### 5.5 Free-first policy

1. **Quality bar per role.** R1 builds eval sets: about 100 reflex utterances (answers and quick
   tool calls) and about 30 agent tasks with stubbed tools. A model joins a chain only if it meets
   the bar (tool-call validity, task success, and the latency budget for reflex).
2. **Order:** passing free models first, ordered by measured quality then latency; paid last and
   only when enabled.
3. **Fallthrough:** rate limit / quota / provider error / timeout / failed quality check → next entry.
   Health per provider key is tracked in Redis (circuit breaker, cooldown).
4. **Free capacity at scale (production concern):** free tiers are per account and small
   (`RESEARCH.md` §5). In production, free capacity comes from each user's own free keys (a guided
   "get a free Groq key" flow, ~1 minute), on-device compute, and a small platform pool. Then paid.
5. **Data terms:** Gemini's free tier uses prompts to improve Google products. Onboarding asks the
   user whether to allow such providers; if not, they're skipped.
6. **Re-evaluate monthly.** Free offers change (Cerebras and Gemini both cut theirs in 2026). The
   eval runs in CI against each chain entry.

## 6. Orchestration

### 6.1 Jobs
A **job** is one delegated task: thread, status, steps (tool calls), todo list, usage. It runs as
an asyncio task in the brain, and its state is persisted to Postgres at every step so a restart
resumes or cleanly fails it, never silently drops it.

### 6.2 Concurrency & resource limits
- Per-user limits: max concurrent jobs (plan-based, default 3), max tool calls per job, token
  budget per job (`task_budget` beta on the agent).
- Global: semaphores per provider and model; Redis token-bucket rate limits per user and provider.
- Per-device: a tool call targets a device that is online and has the capability (§7.3).
  Offline device → the agent is told so it can pick another device or ask.

### 6.3 Scheduling
`schedules` table (cron / one-shot) + a brain loop claiming due rows with `SELECT … FOR UPDATE
SKIP LOCKED`. A schedule fires a signal into the user's thread (e.g. "morning briefing") exactly
like a spoken one.

### 6.4 Signal router (never ignore a signal)
On each `signal.final` while jobs are running, the reflex classifies it as one of:
- **interrupt/cancel** ("stop", "never mind") → cancel the named or most recent job
- **steer** ("use my work email instead") → appended to the running job as a user message
- **new** → handled normally; a new job runs in parallel if needed
- **status** ("how's it going") → answered from job state, no LLM call to the agent

Every signal gets an `ack` event within the latency budget, even if the answer is "I'm still on the
last thing, I'll get to this next."

## 7. Tools

### 7.1 Contract

```python
class ToolSpec:
    name: str                    # snake_case, <noun>_<verb>
    description: str             # written for the model: when to use it, what it returns
    input_schema: dict           # JSON Schema, strict (additionalProperties: false)
    target: Literal["brain", "device"]
    risk: Literal["read", "write", "destructive", "external"]
    parallel_safe: bool          # read-only tools: True
    requires: set[str]           # device capabilities, e.g. {"windows"}, {"adb"}
    timeout_s: float
    defer_loading: bool          # long-tail tools are found via tool search
```

- **Brain tools** are Python functions in `brain/app/tools/` and `brain/app/integrations/`.
- **Device tools** are declared in the brain (the model sees one catalog) and implemented in
  `spark-body`. The brain sends `tool.call`; the device replies `tool.result` (§9).
- Tool results are what the tool actually got. Empty means empty. Errors are readable
  (`is_error: true`).

### 7.2 Permission engine (Claude Code style)

- Modes: `default` (read runs, write runs if reversible, destructive/external ask), `ask` (everything
  asks), `trust` (nothing asks except purchases and payments, which always ask).
- Rules: `allow` / `ask` / `deny` per tool, with optional argument patterns, e.g.
  `shell(git status*)`, `file_delete(C:/Users/*/Downloads/**)`, `adb_shell(pm list *)`.
  Scope: user, or user + device. Saying "always allow" adds an `allow` rule.
- Approvals go to all of the user's online devices; the first answer wins; there's a timeout.
- **Hooks:** `pre_tool` (deny, rewrite, audit) and `post_tool` (redact secrets, audit log) as
  plain Python callables registered in the brain.

### 7.3 Capability catalog at launch

| Area | Tools (risk) | Where |
|---|---|---|
| System | volume, brightness, media keys, power/sleep/lock, battery, network, bluetooth toggle, notifications, screenshot (read/write) | device |
| Apps & processes | app_open/close/focus/list, process_list/kill (write/destructive) | device |
| Files | file_read, file_write, file_edit, file_move, file_delete, glob, grep, folder_organize + restore | device |
| Shell | shell (PowerShell/cmd; destructive by default, allow-rules relax it) | device |
| Input & screen | keyboard type/hotkey, mouse; screenshot → image to the model (the eye's first step) | device |
| Browser | browser agent over CDP in the user's own browser (port of `plugins/installed/web/browser`) | device |
| Phone (ADB) | adb_devices, adb_shell, adb_screencap (image), adb_input (tap/swipe/text), adb_install, adb_push/pull | device |
| Web | web_search, web_fetch (SearXNG + DuckDuckGo + own fetcher; Anthropic server tools as paid last resort); places/hotels/products entity search (OpenStreetMap first) | brain |
| Google | gmail_search/read/send/draft, calendar_list/create/update/delete, drive_search/read/upload | brain |
| Slack, Notion | read/search/post | brain |
| MCP | user-connected remote MCP servers via the Messages API MCP connector | brain |
| Self | remember, recall, forget, set_language, settings_update, schedule_create/list/delete, todo_write, ask_user, task (sub-agent), delegate | brain |

Later: computer use (`computer_toolset_20260801`) for full GUI control once the eye phase starts.

## 8. Memory & Learning

- **Short-term:** thread messages (Postgres) + last N turns hot in Redis.
- **Long-term facts:** after each completed turn, a background call on the sub-agent chain (free first) extracts candidate
  memories (preferences, people, routines, corrections) as structured output. They're deduplicated
  against existing memories and upserted with `importance`, `source_message_id`, and timestamps.
- **Profile:** a short always-in-prompt summary per user (like `CLAUDE.md` for the user),
  regenerated when memories change materially.
- **Retrieval:** hybrid search, pgvector HNSW (cosine) + Postgres full-text, fused by rank,
  top-k = 8, filtered by `user_id`. Embeddings come from a small multilingual ONNX model (384-d)
  in the brain process (~5 ms on CPU, no network). Runs on partial transcripts so results are
  ready at endpoint.
- **Explicit control:** `remember` / `forget`, and a Memory page in Settings to view, edit, and delete.
- **Decay:** `last_used_at` boosts ranking; unused low-importance memories expire.

## 9. Device Gateway Protocol (v2)

The full event list with payloads is in **`API.md` §3** (the source of truth). In short: one Socket.IO
connection per device on namespace `/v2`, authenticated with the access JWT + `device_id`. Devices send
signals, tool results, approvals, wake claims, and engine plans; the brain sends reply deltas, cues,
tool calls, approval/ask/connect requests, job updates, and notices. Large outputs go over signed HTTP uploads.

## 10. Sync

The brain is the source of truth. Threads, messages, jobs, settings, permissions, and memories
live in Postgres. Every change is pushed to all of the user's online devices (`settings.changed`,
`job.update`, new messages). A reconnecting device sends `last_event_id` and gets missed events from
a Postgres-backed event log (kept 7 days). "Do it on my phone" works because the agent picks the
target device for each device tool call.

## 11. Local Fallback (desktop)

- **Detection:** brain socket down, `/health` failing, or LLM provider errors past the retry
  budget → Electron shows a banner and Spark says: "I can't reach my cloud brain, so I'm using
  the local model. I can only do basic things on this computer for now."
- **Local brain:** `spark-body` runs llama.cpp (port of `llms/`) behind the OpenAI-compatible
  adapter, with a small tool loop limited to low-risk device tools (no integrations, no shell
  without approval).
- **Models page:** detects hardware (RAM, VRAM, CPU; port of `llms/` hardware-aware selection),
  recommends a model, searches Hugging Face GGUF, downloads with progress and resume, verifies the
  checksum, and auto-configures. Onboarding links here.
- **Recovery:** on brain reconnect, local-only turns are uploaded to the thread so memory and
  history stay complete.

## 12. Identity, Security, Usage

- **Auth:** email OTP (hashed, 5 attempts, cooldown) and Google OAuth (OIDC). Access JWT (15 min,
  secret from env/secret store) and rotating refresh tokens stored hashed per device in `sessions`.
  The desktop keeps its refresh token in the OS keychain.
- **Every** HTTP route and socket event resolves the user from the verified token. No route accepts
  `user_id` from clients. CORS limited to the app origins. All traffic over HTTPS via Caddy.
- **Secrets at rest:** BYOK keys and OAuth refresh tokens encrypted with AES-GCM under a master
  key from env (KMS later). APIs return only provider name and last 4 characters.
- **Usage:** every LLM call, STT/TTS cloud minute, and paid tool call writes a `usage_events` row
  (tokens by model, cost estimate). Daily quotas by plan are checked before each call; BYOK calls
  are metered but not counted against platform quota.
- **Google restricted scopes:** a public app with Gmail read/send scopes needs Google OAuth
  verification plus an annual third-party security assessment (CASA). Budget time for it before
  public launch. Beta testers can be added as test users until then.

## 13. Observability

- Every signal gets a `trace_id` carried device → brain → tools → device. Spans: endpoint,
  prefetch, reflex TTFT, first sentence, TTS first audio (reported back by the device), each tool
  call, each agent turn.
- Structured JSON logs with secrets redacted by a `post_tool` hook and the log formatter.
- Dashboard: p50/p95 first-audio latency, reflex TTFT, cache hit rate
  (`usage.cache_read_input_tokens`), tool error rate, cost per user per day.
- Error reporting (opt-in) for brain, Electron, and body.

## 14. Data Model (Postgres)

The full schema, Redis keys, device-local stores, and retention are in **`DATABASE.md`** (the source of
truth). Core groups: identity & devices, conversation & work (threads, messages, jobs, steps, approvals,
artifacts, schedules), memory (pgvector + full-text), capabilities & access (rules, skills, plugins, MCP,
keys, OAuth), operations (usage, incidents, sync events, audit).

## 15. Repository Layout (v2)

See **`FOLDER_STRUCTURE.md`**: `brain/` (cloud), `body/` (device sidecar), `electron/` (desktop shell +
UI), `deploy/` (compose, Caddy). v1 folders stay runnable for reference until each phase replaces them.

## 16. What We Keep from v1

| v1 piece | v2 fate |
|---|---|
| Tool implementations (system, files, apps, Gmail, Calendar, Drive, Slack, Notion, browser agent, folder organize) | Ported to the `ToolSpec` contract; device ones move to `body/hands`, brain ones to `brain/integrations` |
| Sentence-chunk splitter (`stream_service`) | Ported to the reflex streamer |
| Speculative prefetch, interrupt handling | Concepts kept, reimplemented on `signal.partial` / `signal.interrupt` |
| `job_coordinator`, `approval_coordinator`, `failure_classifier` semantics | Folded into `jobs/` and `tools/permissions.py` |
| Wake word models, VAD settings, voice daemon logic | Moved into `body/ear` |
| `llms/` hardware-aware model selection | Moved into `body/local_brain` |
| Electron windows, tray, keytar, design tokens, onboarding | Kept; socket protocol switched to v2 |
| v1 provider router (`routing_config.py`, key rotation, quota flags) | Idea kept as free-first chains (§5.3); the eight per-provider clients collapse into two adapters |
| PQH/SQH split, MongoDB, LanceDB, Pinecone, Upstash, YAML skills, `server/tools` legacy tree | Dropped |

## 17. Spark's Voice (persona)

Spark talks like a sharp, relaxed friend: human, chill, honest. Spoken replies lead with the
answer, use short sentences and everyday words, rotate their acknowledgements, match the user's
energy, and end finished work with a human wrap-up: what got done, anything that needs the user,
and an optional next step. Tone tags (`[chill]`, `[serious]`…) drive expressive voices. Style never
overrides honesty: the grounding check wins. The full guide, with the phrase bank and banned
phrases, is **`PERSONA.md`**. It's enforced by the persona block in every system prompt, a
post-hook lint, and the persona eval.

---

# Part 2 — Per-device engines, resilience, capabilities, UI

## 18. Device Fitness & Engine Plans

**Rule:** no engine is used on a device until it has proven, **on that device**, that it fits
the latency budget. Benchmarks show the same engine ranging from < 1 s to ~3.5 s to first audio on
different CPUs (`RESEARCH.md` §6), so a fixed choice can't hold the 1 s target.

### 18.1 When fitness is measured
| Trigger | What runs |
|---|---|
| First run (onboarding, ~30–60 s, with a progress screen) | full suite: hardware scan + every candidate engine |
| Every app start | quick check (~2 s): hardware/power state + one short probe for each currently selected engine |
| Power or hardware change (unplugged, battery saver, GPU/driver change, new mic) | re-probe the affected roles |
| Continuously | every real call reports its measured latency; scores update as a moving average (EWMA) |
| Weekly / after an app update / on demand ("Run benchmark" in Engines) | full suite |

### 18.2 What is measured
- **Hardware:** CPU model, cores, AVX2/AVX-512, RAM free, GPU and VRAM (CUDA / DirectML), power state.
- **Network:** RTT to the brain, the Groq API, and the edge-tts endpoint; packet loss.
- **STT candidates:** final-transcript latency after endpoint, real-time factor, word error rate on
  bundled test clips.
- **TTS candidates:** time to first audio for a standard 12-word sentence, real-time factor, success
  rate, and expressiveness support (vocal-direction tags or not).
- **Local LLM candidates:** time to first token and tokens/s for a fixed prompt.

### 18.3 Selection
For each role (`stt`, `tts`, `local_llm`, and `wake/vad`, which always runs locally):
1. Split candidates by the role budget (TTS first audio ≤ 250 ms, STT final ≤ 300 ms after
   endpoint, local reflex first token ≤ 400 ms). Low-spec devices (hardware tier 0) get a 700 ms TTS
   budget: their target is first audio within 2 s, not 1 s.
2. Drop candidates outside the cost policy (paid off during build) or out of quota.
3. Rank what fits: TTS by **expressiveness, then latency**; STT by **accuracy, then latency**. The
   working candidates that miss the budget follow, fastest first, as last-resort fallbacks (late
   speech beats silence).
4. Result: an **engine plan**, an ordered list per role, stored in `devices.engine_plan` and sent to
   the brain. The brain uses it too, for example to keep replies short on a slow-TTS device.

On-device models are downloaded per hardware tier from a pinned catalog (`body/spark_body/models.py`,
sherpa-onnx on CPU) and then benchmarked like any engine. Measured on a low-spec laptop: fp32
models ran ~4× faster than int8 (no VNNI); Piper ~150 ms per sentence, Kokoro ~1.7 s; Moonshine-tiny
~120 ms per command at ~10% WER.

TTS candidate order before benchmarking: Groq Orpheus (expressive vocal directions, ~200 ms, free
100 clips/day per account) → edge-tts from the device (free, fast, natural; unofficial, so
health-checked) → Pocket TTS / Chatterbox-Nano / Kokoro (local) → Piper (fastest local fallback).
Spark's replies carry tone tags (v1 used `[calmly]`). Engines that support vocal directions get
them; the others have them stripped.

### 18.4 Live switching
If the selected engine misses its budget twice in a row, or returns nothing, the device switches to
the next engine in the plan **for the current sentence**, and the supervisor records it (§19). The
Engines page shows why ("edge-tts returned 503 → switched to Kokoro for 10 min").

## 19. Supervisor — Spark Never Fails Silently

A per-user **Supervisor** runs in the brain (an asyncio actor per active user) and a matching
**watchdog** runs in `spark-body`. Together they watch every signal, job, tool call, and engine
against an expected timeline.

### 19.1 What it watches
| Watch | Expectation | Example failure |
|---|---|---|
| Signal timeline | ack ≤ 300 ms, first audio ≤ budget from the device plan | provider slow, TTS late |
| Streams | tokens keep flowing (gap ≤ 1.5 s) | stalled LLM stream |
| Outputs | non-empty and valid: transcript has text, TTS produced audio, LLM produced text or a tool call, tool output matches its schema | engine "succeeded" with nothing |
| Grounding | a summary only names items present in tool outputs | v1 calendar/email hallucination |
| Tools | finish before `timeout_s`; the target device stays online | device went to sleep mid-job |
| Loops and budgets | no identical tool call repeated 3×; step, token, and time budgets per job | agent stuck |
| Health | per provider / engine / device: error rate, latency EWMA, quota left | Groq daily quota exhausted |
| Estimates | the duration estimate for a job matches reality within 2× | "should take 5 s" is now 30 s |

### 19.2 Remedies (playbook, tried in order)
1. **Hedge:** if a stage nears its deadline, start the same request on the next chain entry in
   parallel and take whichever answers first (reflex LLM, cloud STT/TTS).
2. **Switch:** retry on the next provider or engine (circuit breaker opens for the failed one).
3. **Bridge:** play the local "heard-you" earcon or a short cached filler so the user isn't left in silence.
4. **Degrade:** text-only display if all TTS fails; shorter answers on slow devices; local model if
   the cloud is unreachable (§11).
5. **Re-route:** move a device tool to another online device of the user, if one has the capability.
6. **Re-plan:** tell the agent what failed and why (as a tool error) so it can choose another path.
7. **Ask:** `ask_user` when only the user can unblock it (re-connect Gmail, pick a device).
8. **Fail explicitly:** a spoken and visible message with the reason and a next step. Never silence.

**Invariant:** every signal and job reaches a terminal state (`answered`, `done`, `cancelled`,
`failed_explained`) within its deadline. A background check (every 5 s) finds anything without a
terminal state past its deadline and runs the playbook on it.

### 19.3 Learning from incidents
Every incident is stored (`incidents` table: user, device, stage, engine/provider, error, remedy,
outcome). It feeds the health scores and the device engine plan, and repeated patterns show in the
Engines page. Chaos tests in CI kill providers, add latency, and return empty outputs, and they
assert the invariant holds.

## 20. Capabilities Platform: Tools, Skills, Plugins, MCP, Hooks

Built on what Claude Code and Codex do (`RESEARCH.md` §1–§3), with standards Spark can share
with them.

### 20.1 Tools
`ToolSpec` (§7.1) plus MCP-compatible fields: `title`, `output_schema`, `annotations`
(`read_only`, `destructive`, `idempotent`, `open_world`), and `response_format`
(`concise` | `detailed`). Built-in tools follow the Anthropic tool-writing guide: workflow-shaped,
namespaced (`gmail_search`, `calendar_create_event`), readable fields instead of raw ids, and
actionable errors.

### 20.2 Skills (Agent Skills open standard)
- Format: a `SKILL.md` folder with `name`, `description`, and optional `scripts/`, `references/`,
  `assets/`, the same standard as Claude Code and Codex. **Users can import skills made for
  either one.**
- Progressive disclosure: only name + description sit in context (catalog capped at 2% of the
  context window, descriptions ≤ 1,024 chars); the body loads when the skill is selected;
  references load on demand; scripts run in the device or brain sandbox and are never loaded.
- `disable-model-invocation` for side-effecting skills ("/morning-briefing"), `allowed-tools` for
  pre-approved tools inside a skill.
- Built-in skills: `skill-creator` ("Spark, make this a skill"), plus starter skills (morning
  briefing, inbox triage, meeting prep, file cleanup, research report).
- Storage: `skills` table (user scope) + plugin-provided skills; files in object storage.

### 20.3 Plugins
- A plugin bundles skills, tools (MCP servers), hooks, and sub-agent definitions, with a manifest
  (`spark-plugin.json`, readable alongside `.claude-plugin/plugin.json` so compatible Claude Code
  plugins can be imported).
- Marketplaces are git repos with a `marketplace.json`. Spark ships an official marketplace, and
  users can add others.
- Before install, Spark shows the plugin's **context cost** (tokens its catalog adds per turn),
  required permissions, and trust tier (official / community / third-party).
- Enable/disable per user and per device; updates pinned by version.

### 20.4 MCP
- **Remote servers (brain):** streamable HTTP with OAuth (RFC 9728 / 8414 discovery, token
  refresh), connected from the Capabilities page; tokens encrypted per user.
- **Local servers (device):** stdio servers run by `spark-body` (filesystem, local DBs, IDE tools),
  surfaced to the brain as device tools.
- **Discovery:** search the official MCP Registry from the Capabilities page.
- **Mapping:** tools are named `mcp__<server>__<tool>`. Annotations map to risk levels but are
  **untrusted** unless the server is marked trusted, so untrusted servers default to "ask".
  Per-server and per-tool approval modes are `auto` / `ask` / `writes` / `deny`.
- **Output limits:** warn at 10k tokens, cap at 25k. Larger results go to the artifact store with a
  preview + handle (`artifact_read(handle, range)`).
- **Elicitation:** `input_required` results render as Spark's `ask_user` UI or voice prompt.
- **Deterministic tool ordering** for prompt-cache hits.

### 20.5 Hooks
Brain-side hook events: `signal_received`, `pre_tool`, `post_tool`, `post_tool_batch`,
`permission_request`, `job_start`, `job_end`, `pre_compact`, `memory_write`. Handlers are Python
callables (built-in) or user-defined **automations** (HTTP webhook or a skill). Decisions: allow /
deny / ask / rewrite input / add context / replace output. Built-in hooks: secret redaction, audit
log, grounding check (§19), cost meter.

### 20.6 Permission engine (extends §7.2)
- Precedence **deny → ask → allow**; a bare-tool deny removes the tool from the model's context.
- **Auto-reviewer:** for medium-risk calls in `default` mode, a cheap model checks the call against
  the user's actual request and either allows it or escalates to ask (Claude Code's auto-mode
  classifier, Codex's `auto_review`). Destructive, purchase, and send actions always ask unless an
  explicit allow rule exists.
- The approval UI shows the exact inputs (recipient, file path, command) before running.

## 21. Efficiency: Tokens, Latency, Accuracy

| Lever | Rule |
|---|---|
| Tool catalog | core ~20 tools always loaded; the rest found by tool search (Claude) or a local BM25 + embedding pre-selector (free models: top 8 tools for the task) |
| Skill catalog | ≤ 2% of the context window; bodies on demand |
| Tool outputs | `concise` by default; paginate and filter; 25k-token cap; overflow → artifact + preview + handle |
| Prompt caching | deterministic tool order, static prompt first, volatile context last |
| Sub-agents | heavy reading (inbox, research, file trees) happens in sub-agents; only summaries return |
| **Workflow mode** (code execution) | for multi-tool data flows (e.g. "move every invoice email's attachment to Drive and log it in a sheet") the agent writes a Python script that calls tools as functions inside a sandbox, so intermediate data never enters the context (Anthropic measured −98.7% tokens). Device sandbox for local data, brain sandbox (container) for cloud data. Working scripts can be saved as skills |
| Memory | profile ≤ 300 tokens in the prompt; top-8 retrieval; memories from threads that touched external content need confirmation before saving (Codex governance) |
| Accuracy | strict schemas, validation before execution, grounding check before speaking, evals per role in CI |
| Latency | reflex never waits on tools; parallel tool calls; hedged requests; prefetch on partial transcripts |

## 22. Data Interpretation, Research & Artifacts

### 22.1 Input types
| Input | Pipeline (free first) |
|---|---|
| Text, documents (PDF, DOCX, XLSX, CSV, PPTX) | parsed on the device (pypdf / python-docx / pandas); large tables go to workflow mode, not the context |
| Images, screenshots, phone screencaps | vision model (Gemini Flash-Lite free if allowed → local vision model on fit devices; Claude later) |
| Audio files | transcribed on the device (local Whisper-class model) → text; speaker and timestamp segments kept |
| Video | ffmpeg on the device: keyframes (scene-change sampling) + audio transcript → vision + text model; Gemini native video as an option when allowed |
| Charts / graphs (reading) | vision model + any extracted underlying data |
| Mixed ("compare this chart to the numbers in my sheet") | each part through its pipeline, then one agent turn with all extracted parts |

### 22.2 Research ("search" done properly)
1. Plan 3–6 queries from the question (reflex or sub-agent).
2. Search SearXNG + DuckDuckGo in parallel, then dedupe and rank by domain quality + embedding
   similarity (local model).
3. Fetch the top N in parallel; extract the main content (readability / trafilatura).
4. Chunk; keep only the passages most relevant to the question (local embeddings), never whole pages.
5. Answer with inline citations; a sources list in the UI.
6. Deep research = a sub-agent fan-out over sub-questions, then synthesis.

### 22.3 Outputs: artifacts
Every non-trivial result is a typed **artifact** shown in the UI and saved to the thread: `table`,
`chart` (Vega-Lite spec rendered interactively), `image`, `audio`, `video`, `document`, `code`,
`map`, `entity_cards`, `citations`. Each artifact can be exported (CSV, PNG, PDF, DOCX), opened in
its app, or used in a follow-up command. Charts come from workflow mode (pandas → Vega-Lite spec),
not hand-written by the model.

## 23. Connecting Accounts (Gmail and friends) — Effortless UX

- **One "Connect Google" button** covering Gmail, Calendar, and Drive with incremental scopes; the
  user can sign in with Google and connect in the same step.
- **Just-in-time connect:** when a request needs an account that isn't connected, Spark says
  "I need access to your Gmail for that" and shows an inline **Connect** card in the
  conversation. OAuth opens in the system browser. On return the job **resumes automatically**,
  so the user doesn't repeat the request.
- **Health:** token expiry, revoked access, and missing scopes show as a banner with a one-click
  **Reconnect** (never a raw error like v1's "No active gmail token for user me").
- **Least privilege:** read scopes first; send/modify scopes requested the first time a send/modify
  is needed.
- **Beta reality:** until Google verification + CASA (§12) is done, beta users are added as test
  users. The connect screen explains Google's "unverified app" warning in one line with a screenshot.

## 24. Desktop UI Redesign

Clean, professional, five destinations. Related settings are grouped instead of getting one tab
each.

```
┌──────┬────────────────────────────────────────────────────────────────────┐
│ Home │  SPARK (Home)                                                      │
│      │  ┌──────────────── conversation ───────────────┐ ┌─ live panel ──┐ │
│ Acti-│  │ you: summarize my unread mail               │ │ Job: Inbox    │ │
│ vity │  │ spark: 5 unread, 2 need replies…   [cite]   │ │ [x] fetch 20  │ │
│      │  │ ┌ artifact: email table ───────────────┐    │ │ [ ] drafts    │ │
│ Capa-│  │ │ sender | subject | action   [export] │    │ │ (!) approve   │ │
│ bil. │  │ └──────────────────────────────────────┘    │ │ [Stop]        │ │
│      │  └─────────────────────────────────────────────┘ └───────────────┘ │
│ Engi-│  [mic: hold / "Hey Spark"]  [type a message...]      [Ctrl+K]      │
│ nes  │                                                                    │
│ Sett.│                                                                    │
└──────┴────────────────────────────────────────────────────────────────────┘
```

| Destination | Contains |
|---|---|
| **Home** | conversation, inline artifacts, live job panel (todo, steps, approvals, stop), mic/type input, device switcher ("run on: laptop / phone") |
| **Activity** | job history, schedules & automations, incidents (§19), logs |
| **Capabilities** | one searchable hub with filter chips: **Connectors** (Google, Slack, Notion, MCP servers) · **Skills** · **Plugins** · **Tools** (each tool with its risk level + permission rule). A Discover tab for the marketplace and MCP Registry |
| **Engines** | **Models** (brain chains + health, local model download/manage), **Voice** (STT/TTS engines with this device's benchmark scores, voice picker, "Run benchmark"), **Services** (search, places), **Keys** (user free keys, BYOK) |
| **Settings** | account, devices, permissions (mode + rules), privacy (data-training providers toggle, memory page, export/delete), language, verbosity, usage & quota |

Plus a **command palette** (Ctrl+K) that reaches every action and setting, and a compact
**voice overlay** (the v1 AiPanel) for hands-free use. Every list has loading / empty / error
states (`DESIGN.md` §5); every action shows its inputs and result; nothing shows a raw stack trace.
High-fidelity mockups are produced in R2 before UI code is written.

## 25. Language: Auto-Detect & Switching

- Settings: `language` (reply language) and `auto_detect_language` (on/off), synced to every device.
- **Switching by voice:** "switch to Hindi" / "talk to me in English" is a tier-1 intent (no LLM):
  the brain updates settings, pushes `settings.changed`, and every device's fitness module selects
  STT/TTS engines for that language, downloading models through the Models page if needed.
- **Auto-detect:** the STT engine reports the language per utterance. If confidence is high and
  the language is supported, Spark replies in it for that turn; otherwise it replies in the
  setting's language.
- **At launch only English is supported.** A request for another language gets a persona-voiced
  answer ("Hindi's not ready yet, it's on the way. Sticking with English for now.") and nothing breaks.
- The persona stays the same in every language; memories are stored language-neutral; the
  reply language is passed to the LLM in the volatile part of the prompt.
- Adding a language = config + STT/TTS models + a tier-0 grammar + persona eval in that language.

## 26. Request Flows & Cross-Device Control

### 26.1 One account, many bodies
- Every device signs in to the same Spark account (Google sign-in or email OTP), so every device
  of a user shares one `user_id`. Each device registers its `device_id`, `kind` (desktop / mobile),
  a friendly name ("Laptop", "Pixel"), capabilities, its engine plan (§18), and presence (Redis).
- The app keeps running in the tray (desktop) or as a foreground service (Android, later) so the
  ear stays on for the wake word.
- **Phone control before the mobile app exists:** the phone is a sub-device of the laptop over
  ADB (USB or wireless debugging). Its capabilities show as `adb:<serial>`. Once the Spark mobile
  app ships, the phone becomes a full body with its own ear, mouth, and hands, and the same
  commands route straight to it.

### 26.2 Wake-word arbitration (both devices hear "Hey Spark")
1. Each device that detects the wake word starts local STT immediately (no waiting) and sends
   `wake.claim { score, loudness, foreground, ts }`.
2. The brain collects claims for 150 ms and picks one device: the highest score + loudness, with
   ties going to the device in the foreground or used most recently.
3. The winner gets `wake.grant` and continues. The others get `wake.yield`, stop listening, and show
   "answering on Laptop".
4. Arbitration runs while the user is still talking, so it adds no latency.

### 26.3 Choosing the target device
1. **Explicit:** "on my phone", "on the laptop", or a device name → resolve among the user's
   devices. If two phones match, ask once and remember the answer as the default.
2. **Implicit:** device tools run on the **origin device** (where the user spoke).
3. **Capability fallback:** if the origin can't do it (sending an SMS from the laptop), pick an
   online device that can, and say so ("Sending it from your phone.").
4. **Target offline:** say so and offer an alternative (ADB if the phone is plugged in) or a queued
   run ("I'll do it when your phone is back online", expires in 1 h).

**Where the answer appears:** the origin device speaks it. The target device shows a quiet
notice ("Spark opened YouTube, asked from Laptop"). The shared thread updates on every device.

### 26.4 The flows

**A. Simple command (no LLM), e.g. "Hey Spark, volume to 30", "pause the music", "next song"**
```
wake → VAD → STT on device → reflex arc matches (≥ 0.92 confidence, all slots filled)
     → run the tool on the device ──────────────── ~150–300 ms after end of speech
     → chime + UI tick (or a short templated phrase)
     → signal.handled_locally → brain (history, memory, incidents stay complete)
```

**B. Normal conversation, e.g. "What's a good name for a coffee shop in Kathmandu?"**
```
wake → STT (partials stream to the brain → memory prefetch)
     → reflex arc: no match → signal.final → brain router → reflex LLM (hedged)
     → reply.delta sentence by sentence → TTS on device ── first audio ≤ 1 s
     → background: memory extraction from the turn
```

**C. Action that needs understanding, e.g. "Open Spotify and play something calm"**
```
→ reflex LLM streams "Playing something calm on Spotify." and in the same response calls
  media_play(app="spotify", query="calm") on the origin device, in parallel with the speech
→ device runs it → tool.result → done chime (§4.4)
```

**D. Multi-step work, e.g. "Find my last invoice email and save the PDF to Downloads"**
```
→ reflex LLM: "On it, looking for your latest invoice." + delegate(task)
→ agent loop: gmail_search (brain) → gmail_get_attachment (brain)
             → file_write(Downloads/…) on the origin device (reversible write → auto-allowed)
→ job panel shows steps live; spoken summary built from the tool outputs
→ Gmail not connected? an inline Connect card appears; the job resumes after OAuth (§23)
```

**E. Cross-device, spoken to the laptop: "Open YouTube on my phone and play lo-fi"**
```
→ reflex arc matches open_app + target=phone + query, or the reflex LLM parses it
→ target resolution: phone = adb:<serial> via Laptop (now) | phone body (later)
→ laptop speaks "Playing lo-fi on YouTube on your phone." in parallel with
  adb: am start (YouTube search intent) → tool.result → chime
→ extra cost: one brain → device hop (~50–80 ms); the spoken ack doesn't wait for it
```

**F. Cross-device, spoken to the phone (mobile app, later): "Pause the music on my laptop"**
```
→ phone STT → reflex arc matches media_pause + target=laptop
→ brain routes tool.call to Laptop (no LLM) → phone speaks "Paused on your laptop."
```

**G. Handoffs**
- "Send this to my phone": the origin uploads an artifact, and the phone gets a notification and download.
- "Open on my laptop what I'm reading on my phone": phone `current_url` → laptop `open_url`.
- "Continue this on my phone": the thread is shared, so the phone opens it at the same spot.

**H. Something goes wrong** (any flow): the supervisor (§19) hedges, switches, re-routes, asks, or
explains. No path ends in silence.

## 27. Reflex Arc — Skip the LLM When It Isn't Needed

Like a spinal reflex: simple, unambiguous commands are handled by the body, and the brain is only
told afterwards. The LLM is used only where language understanding or reasoning is needed. **Rule:**
a tier may handle a signal only when it is sure. Any doubt goes up a tier, so UX never drops.

| Tier | Where | Handles | LLM | Typical latency |
|---|---|---|---|---|
| **0. Reflex arc** | device | closed set of intents with slots: media (play/pause/next/prev/volume/mute), system (brightness, lock, sleep, screenshot, Wi-Fi/Bluetooth toggles), open/close/switch app (resolved against the installed-app index), timers/alarms, time/date/battery, "stop / cancel / never mind / repeat that / louder" | none | ~150–300 ms |
| **1. Brain router** | brain | tier-0 intents with a device target ("on my phone"), job status ("how's it going"), approvals ("yes, do it"), answers to a pending `ask_user`, slash-style skills and automations, cached tool results (weather 10 min, places 1 day) | none | ~200–400 ms |
| **2. Reflex LLM** | brain | conversation, actions needing understanding, anything tiers 0–1 aren't sure about | fast free model | first audio ≤ 1 s |
| **3. Agent** | brain | multi-step tool work, research, analysis | stronger free model | streamed progress |

**How tier 0 decides (sure-or-escalate):**
- A grammar for the common phrasings, plus a small local embedding classifier (the same ONNX model
  family as the brain's, ~5–15 ms) with negative examples ("play a song that fits my mood" is not
  tier 0).
- Accepted only if the classifier confidence is ≥ 0.92, every slot is resolved, the app or device
  named exists, and the action is reversible. Anything destructive, sending, or purchasing always goes up.
- Replies use short templated phrases with natural variation, or just the chime (§4.4). They're
  spoken by the device's own TTS.
- If a tier-0 action fails, the signal and the error go to the brain, and tier 2 handles it as if it
  had gone there first.
- **Measured, not assumed:** an R1 eval of ~300 utterances (positives, near-misses, negatives) must show
  a false-accept rate < 0.5%. Spark Logs shows the share of signals each tier handled.

**What stays on the LLM (never short-circuited):** anything open-ended, ambiguous, multi-intent,
needing memory or reasoning, or touching other people (messages, email, calendar invites).

## 28. Open Items (defaults apply unless the owner changes them)

| Item | Default |
|---|---|
| Brain region | decided by the R7 benchmark (§4.3); development runs on the laptop |
| Free-beta quota | 200 reflex turns + 30 agent jobs / user / day |
| Agent effort default | `medium` |
| On-device STT model | benchmark Parakeet vs Moonshine in R1 on a mid-range Windows laptop |
| Paid providers | off during the build (`PAID_PROVIDERS_ENABLED=false`); turned on for production or when Claude startup credits arrive |
| Premium voice | Groq Orpheus free quota first; Cartesia/ElevenLabs only after paid providers are on and the user opts in |
| Free chain order | decided by the R1 eval + latency benchmark (§5.5) |
| Mobile | protocol ready from R0; app after desktop v1.0 |
