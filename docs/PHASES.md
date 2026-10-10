# PHASES.md — v2 Roadmap

**Product:** Spark: cloud brain + desktop body (mobile later)
**Design:** `REDESIGN.md` (read it first)
**Replanned:** 2026-10-09, replacing the v1 hardening roadmap

---

## How to Use This File

1. Work **one phase at a time**, in order. Each phase ends with something that runs end to end.
2. Check off every ☐ deliverable and pass every ☐ acceptance test before moving on.
3. Update `MEMORY.md` after each completed item; add a `CHANGELOG.md` entry at phase end.
4. v1 code (`server/`, `voice_daemon/`, `llms/`, `electron/action_executor`) is reference material.
   Port from it, don't extend it. Delete each v1 piece in the phase that replaces it.
5. **Free first:** whenever a phase picks a model or service, try the free option first and use
   paid only if the free one misses the bar (`REDESIGN.md` §5.5).
6. **Build stage = free plans only.** `PAID_PROVIDERS_ENABLED=false` until production or Claude
   startup credits. No phase may depend on a paid provider to pass its acceptance tests.

## Where it runs

| Stage | Brain runs on | Why |
|---|---|---|
| **R0–R6 (development)** | **your laptop** (Docker Compose for Postgres/Redis/SearXNG + brain) | free, fastest iteration; the desktop body talks to `127.0.0.1` |
| Testing a second device on the same Wi-Fi | your laptop, reached over the LAN IP | second desktop, or the mobile app later |
| Testing from outside home, or OAuth that needs an HTTPS redirect (e.g. Slack) | your laptop through a **free Cloudflare Tunnel** | a temporary public HTTPS URL, no server needed |
| R7 beta / production | a VPS in the benchmarked region | always-on for real users |

Dev latency differs from production: brain↔device is ~0 ms on the laptop, while the laptop→provider
hop reflects your home network. The real-region numbers come from the R7 benchmark.

## Phase Map

| Phase | Theme | Exit signal |
|---|---|---|
| **R0** | Brain foundations | Desktop signs in to the cloud brain and holds a live v2 socket |
| **R1** | Voice loop < 1 s | "Hey Spark, what time is it?" spoken back in < 1 s p50 |
| **R2** | Agent loop + desktop hands | Multi-step desktop tasks with approvals, progress, and interrupt |
| **R3** | Memory & learning | Spark remembers and uses facts across sessions |
| **R4** | Integrations port | Gmail, Calendar, Drive, Slack, Notion, web, browser agent, ADB |
| **R5** | Local fallback | Brain down → Spark says so and runs on a downloaded local model |
| **R6** | Accounts, quotas, BYOK, language | Usage-metered free beta with settings sync |
| **R7** | Ship | Signed installer, VPS production deploy, monitoring, v1.0 |

---

## R0 — Brain Foundations

### Deliverables
- ☑ `brain/` skeleton per `REDESIGN.md` §15; FastAPI + Socket.IO `/v2`; config from env; structured logs
- ☑ `deploy/docker-compose.yml`: brain, Postgres 16 + pgvector, Redis, SearXNG, Caddy (HTTPS; stub behind the `tls` profile until R7)
- ☑ SQLAlchemy 2.0 async models + Alembic migration for `users`, `auth_identities`, `otp_codes`,
  `sessions`, `devices`, `user_settings`, `threads`, `messages`, `events`, `audit_log`
- ☑ Auth: email OTP (hashed, 5 attempts, cooldown, Resend) + Google sign-in; access JWT (15 min,
  secret from env) + rotating per-device refresh tokens (stored hashed)
- ☑ Device registration + `device.hello` + presence in Redis
- ☑ Electron: sign-in against the brain, refresh token in keychain, v2 socket in main process,
  connection status in UI
- ☑ CI (GitHub Actions): brain tests (pytest), Electron lint + typecheck
- ☑ Test harness (`TESTING.md` §2): FakeProvider, FakeDevice, Clock, test DB compose; the X1 route sweep
- ☑ Everything runs on the dev laptop: `docker compose up` (Postgres, Redis, SearXNG) + brain +
  Electron (+ body from R1). No cloud hosting until R7 (see "Where it runs" above)

### Acceptance Tests
- ☑ No route or socket event accepts a client-supplied `user_id` (test sweeps every route)
- ☑ Refresh token reuse → session revoked; refresh token can't open a socket
- ☑ 6th wrong OTP → locked; OTP stored only as a hash
- ☑ Two devices of one user both receive a `settings.changed` event
- ☑ `docker compose up` on the dev laptop → `/health` green; the desktop app signs in to the local brain

---

## R1 — Voice Loop Under 1 Second

Target per device: first audio within 1 s of the end of speech, within 2 s on low-spec PCs
(owner's call, 2026-10-10; `models.tier` 0, e.g. the owner's Ryzen 7 4700U / 8 GB laptop).

### Deliverables
- ☑ `body/` sidecar: stdio JSON-RPC with Electron main; packaged with its own venv in dev
- ☑ Ear: wake word, VAD, STT engines on-device + Groq Whisper free. Mic + Silero VAD (renderer
  `vad-web`, echo cancellation), endpointer, STT plan with switching, Groq Whisper via the brain
  proxy. Wake word: sherpa-onnx open-vocabulary keyword spotting ("hey/hi/ok spark", no model to
  train; v1's custom `hey_spark.onnx` would have needed training), checked on the device per
  utterance, audio cut after the phrase. On-device STT: Moonshine-tiny (beat Parakeet-110M on
  accuracy: 10% vs 16% WER, ~120 ms); Parakeet-0.6B for strong PCs
- ☑ Mouth: TTS engines Groq Orpheus (free quota), edge-tts (from the device), Pocket TTS / Kokoro /
  Chatterbox-Nano / Piper; sentence streaming; tone tags mapped or stripped; barge-in; echo suppression.
  *Done:* Orpheus (brain proxy), edge-tts, sentence streaming, tone tags, live switching, barge-in,
  echo via Chromium AEC, local Piper (fp32, ~150 ms per sentence on the owner's laptop) and Kokoro
  (strong PCs only: 1.7 s there). Models download per hardware tier (`body/spark_body/models.py`).
  Pocket TTS / Kitten / Chatterbox measured or skipped: too slow on CPU or unclear license
- ☑ **Device fitness** (`REDESIGN.md` §18): hardware scan, per-engine benchmarks, engine plan,
  quick check on every start, re-probe on power change, live EWMA updates, Engines page readout
  (TTS and STT; local-LLM probes join in R5)
- ☑ **Supervisor + device watchdog** core (§19): signal deadlines, hedging, engine switching,
  heard-you earcon, terminal-state invariant, `incidents` table
- ☑ Speak-act-confirm acknowledgements (§4.4)
- ☑ Persona (`PERSONA.md`): persona block in prompts, phrase bank with rotation, banned-phrase post-hook, persona eval
  (rule checks; a judge for naturalness later)
- ☑ **Reflex arc** tier 0 on the device + tier-1 brain router (§27); `signal.handled_locally`
  (tier 1 = stop + language now; job status and approvals arrive with jobs in R2)
- ☑ More free reflex providers behind the latency gate + hedging at 350 ms. Run 2026-10-10 from
  the owner's laptop with 8 Groq keys: gpt-oss-20b TTFT p50 ~450–470 ms / p95 540–820 ms over
  6 runs; 120b ~490 / ~665 ms with tools 33/33 (20b: 31/33). 20b stays first, 120b is the hedge. Nothing meets the 400 ms p95 gate from Nepal (network RTT), accepted under the 2 s
  low-spec target. Mistral's key is out of quota; Cloudflare has no key yet
- ☑ Signal protocol: `signal.partial` / `signal.final` / `signal.interrupt` / `signal.ack` /
  `reply.delta`
- ☑ OpenAI-compatible adapter + Anthropic adapter; chain runner with health and circuit breaker
- ☑ Reflex with quick tools (time, volume, media, open app, brightness) and `delegate` stub
- ☑ Reflex eval set (~100 utterances) and latency benchmark; chain order free first. gpt-oss-20b
  stays first (fastest; final run 50/50 answers, 31/33 tools, 11/12 delegate, persona 45/56
  graded as spoken); the runner rotates keys like the chain
- ☑ Speculative start on endpoint candidate; context prefetch on partials. The live ear
  transcribes after 250 ms of silence and the brain starts the reply then (unless tier 0 will take
  it); its events wait until 700 ms of silence confirms the endpoint, and speech in between cancels
  it (`signal.interrupt`) and is merged and heard again. Gain here 40–110 ms (wake check + cloud STT
  nearly fill the 450 ms window); more on PCs with fast on-device STT
- ☑ Per-signal trace: endpoint, reflex TTFT, first sentence, first audio (device-reported)

### Acceptance Tests
- ☑ `TESTING.md` rows A1–A3, B1–B2, C1, FT1–FT10, WK1–WK3, S1/S6/S8, RA1–RA2, PS1/PS2/PS4 pass.
  Map of every R1 acceptance test to its proof: `TESTING.md` §4.7b
  RA3, RA4, PS3 need jobs and approvals: moved to R2 (owner, 2026-10-10)
- ☑ p50 end-of-speech → first audio < 1000 ms, p95 < 1500 ms over 50 scripted utterances (low-spec
  PCs: p95 < 2000 ms). Owner's low-spec laptop, scripted ear, 2026-10-10: p50 1291, p95 1621 ms
- ☑ "Turn the volume up" → spoken ack and the volume changes, no paid model used when free tiers are healthy
- ☑ Kill the free provider → the next chain entry answers, still under the p95 budget (fakes:
  S6, B2; live: 20b's circuits open → 20/20 answered by gpt-oss-120b, first token p50 469 / p95
  625 ms)
- ☑ Barge-in stops TTS within 150 ms (playback quiet 4–13 ms after the stop + VAD onset)
- ☑ Force the selected TTS engine to return nothing → the next engine speaks the same sentence; an incident is logged (FT4)
- ☑ Throttle the CPU → the fitness check demotes the local engine and the plan changes on the next start
- ☑ Chaos test: 100 signals with random provider failures → every one ends answered or explained, none silent

---

## R2 — Agent Loop + Desktop Hands

### Deliverables
- ☐ Agent loop (`REDESIGN.md` §5.2) on the agent chain; parallel tool calls; escalation rules
- ☐ `ToolSpec` registry; device tool round trip (`tool.call` / `tool.result`) with timeouts
- ☐ Permission engine: modes, deny → ask → allow rules with argument patterns, "always allow",
  multi-device approvals, auto-reviewer for medium-risk calls (§20.6)
- ☐ Hooks: `pre_tool` / `post_tool` (audit, redaction)
- ☐ Jobs: persisted steps, cancel, steer, status; signal router (interrupt / steer / new / status)
- ☐ `todo_write`, `ask_user`, `task` sub-agents, plan approval for risky jobs
- ☐ Desktop hands ported from v1: system, apps/processes, files (+ folder organize restore), shell,
  clipboard, screenshot, keyboard/mouse
- ☐ **UI redesign** (§24): high-fidelity mockups first, then the five destinations (Home, Activity,
  Capabilities, Engines, Settings), command palette, voice overlay; job panel, approval modal, stop
- ☐ Agent eval set (~30 tasks with stubbed tools); set the agent chain order free first
- ☐ Cross-device control (§26): device registry, target resolution, capability fallback, queued
  runs, wake-word arbitration (`wake.claim/grant/yield`), handoffs; tested with two FakeDevices
- ☐ Delete `electron/action_executor/` and `electron/python-service/`

### Acceptance Tests
- ☐ `TESTING.md` rows D1, E1–E4 (phone as a FakeDevice; real ADB lands in R4), F1, G1–G2, W1–W3, T1–T5, S2–S5, S7, RA3, RA4, PS3 (moved from R1) pass
- ☐ "Create notes.txt on the desktop, write my to-dos, open it" completes with progress shown
- ☐ "Delete everything in Downloads" → approval required; deny → nothing deleted
- ☐ "Stop" mid-job cancels within 500 ms; "use the D drive instead" steers the running job
- ☐ 3 independent reads run in parallel (one model turn, three concurrent tool calls)
- ☐ Malformed free-model tool calls twice → escalates to the next chain entry and the job still completes

---

## R3 — Memory & Learning

### Deliverables
- ☐ `memories` table with pgvector HNSW + full-text; local ONNX embedder in the brain
- ☐ Background extraction after each turn (sub-agent chain, structured output), dedupe, importance
- ☐ Profile summary in the reflex/agent prompts; hybrid retrieval prefetched on partials
- ☐ `remember` / `recall` / `forget` tools; Memory page in Settings (view, edit, delete)
- ☐ Prompt-cache layout verified (cache hit rate tracked per role)

### Acceptance Tests
- ☐ "My sister is Asha" → next day "call my sister" resolves Asha
- ☐ Retrieval p95 < 30 ms at 10k memories per user
- ☐ `forget` removes the memory and its embedding; it never resurfaces

---

## R4 — Integrations Port

### Deliverables
- ☐ OAuth connections (encrypted refresh tokens) with **just-in-time connect cards** that resume the
  job after OAuth, one "Connect Google" for Gmail/Calendar/Drive, reconnect banners (§23)
- ☐ Google: Gmail, Calendar, Drive tools; Slack; Notion (ported from v1 plugins)
- ☐ Web: SearXNG + DuckDuckGo search, own fetcher; entity search (OpenStreetMap first)
- ☐ Browser agent on the device over CDP (port v1 `plugins/installed/web/browser`)
- ☐ ADB tools (devices, shell, screencap → image to model, input, install, push/pull)
- ☐ MCP: remote servers (OAuth) in the brain, local stdio servers via the body, MCP Registry search,
  annotation → risk mapping, output caps + overflow to artifacts, elicitation UI (§20.4)
- ☐ Skills (Agent Skills standard, import from Claude Code / Codex), `skill-creator`, starter skills (§20.2)
- ☐ Plugins + marketplace with context-cost display; hooks / automations (§20.3, §20.5)
- ☐ Research pipeline with citations (§22.2); data interpretation for documents, images, audio,
  video (§22.1); artifacts with export (§22.3)
- ☐ Workflow mode: sandboxed Python that calls tools as functions (§21)
- ☐ Scheduler: `schedules` table, reminders, "every morning" briefings
- ☐ Delete `server/` once every v1 tool is ported or explicitly dropped (list in `MEMORY.md`)

### Acceptance Tests
- ☐ Create a calendar event → listing events shows it (v1 bug regression)
- ☐ Empty tool output → reply says nothing was found and never invents items (v1 bug regression)
- ☐ Gmail tools get real message ids; schema validation rejects bad bindings before the API call
- ☐ "Open YouTube on my phone" → ADB opens it on the connected phone (with approval)
- ☐ "Summarize my unread mail" with Gmail not connected → connect card → after OAuth the summary arrives without re-asking
- ☐ A skill copied from a Claude Code or Codex skills folder works unchanged
- ☐ "Analyze this CSV and chart sales by month" → an interactive chart artifact; the raw rows never enter the model context

---

## R5 — Local Fallback

### Deliverables
- ☐ `body/local_brain`: llama.cpp runner (port `llms/`), OpenAI-compatible endpoint, small tool loop
  limited to low-risk device tools
- ☐ Models page: hardware detection, recommendation, Hugging Face GGUF search, resumable download,
  checksum, auto-configure
- ☐ Onboarding step explaining cloud-first + local fallback, linking to the Models page
- ☐ Failure detection → `fallback.notice` banner + spoken notice; uploads local turns on reconnect
- ☐ Delete `llms/` and `voice_daemon/`

### Acceptance Tests
- ☐ Unplug network → Spark says it's using the local model, and "volume up" still works
- ☐ Reconnect → local turns appear in the thread history

---

## R6 — Accounts, Quotas, BYOK, Language

### Deliverables
- ☐ `usage_events` metering for every LLM / STT / TTS / paid tool call; daily quotas by plan
- ☐ BYOK (encrypted, last 4 shown), user free keys tried before platform keys
- ☐ Settings sync: language, voice, permission mode, models; "skip providers that train on data" toggle
- ☐ Language: `set_language` tool, auto-detect setting, per-signal language; English shipped,
  structure ready for Hindi/Nepali
- ☐ Usage page in the app

### Acceptance Tests
- ☐ Quota exhausted → clear spoken + UI message; BYOK lifts it
- ☐ "Switch language to Hindi" → reports it isn't available yet (English only at launch) without breaking

---

## R7 — Ship

### Deliverables
- ☐ Desktop installer (electron-builder NSIS) bundling the body sidecar + embedded Python + models
  (`PRODUCTION.md` §2)
- ☐ Auto-update via GitHub Releases; Windows code signing
- ☐ Region benchmark: rent candidate VPS regions (Mumbai/Singapore vs US-East) for a few hours,
  measure TTFT to the free providers + device RTT, record the choice in `MEMORY.md`
- ☐ Production VPS: backups (Postgres PITR or nightly dumps), secrets, firewall, log retention
- ☐ Dashboards: first-audio latency, TTFT per chain entry, cache hit rate, tool error rate, cost/user/day
- ☐ Google OAuth verification + CASA assessment started for Gmail scopes
- ☐ `PRIVACY_POLICY.md` final (lists free-tier providers' data terms); data export + delete

### Acceptance Tests
- ☐ Clean Windows 11 VM: install → sign in → voice query works, no Python/Node needed
- ☐ Old build auto-updates to the new release
- ☐ Delete my data → no residue in Postgres, Redis, keychain, or app-data

---

## Cross-Phase Rules

- ☐ Every new route / socket event in `REDESIGN.md` §9 (and later `API.md` v2) in the same commit
- ☐ Every table / column in `REDESIGN.md` §14 (and later `DATABASE.md` v2) in the same commit
- ☐ No client-supplied `user_id`; no secrets in code, logs, or responses
- ☐ Every tool: `ToolSpec` with risk level, schema, one test
- ☐ Every scenario in `REDESIGN.md` has a row in the `TESTING.md` §4 matrix and a passing test; phases
  can't close with matrix rows for that phase still red
- ☐ Latency trace on every signal; regressions over budget block the merge
- ☐ Free option tried first; paid usage justified in `MEMORY.md` → Decisions

## Explicitly Deferred

- Mobile app (protocol ready from R0)
- Eye: computer use and continuous vision (screenshot-to-model ships in R2/R4)
- Feel: hardware sensors
- Payments (quotas only during the beta)
- Languages beyond English

_End of PHASES.md_
