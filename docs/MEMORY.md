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
- **R1 done and pushed to `origin/main`** (2026-10-10, fast-forward from `r1/voice-loop`; the
  owner's three mic tests passed after fixes). Every PHASES R1 box ticked. Brain 87 tests (incl. 100-signal chaos), body 60 (Windows CI job; 2 real-model tests run
  only where the models are downloaded), Electron typecheck + lint (0 errors). Acceptance map:
  `TESTING.md` §4.7b. What exists:
  - brain: free-first reflex chain (Groq ×2, Cloudflare, Gemini opt-in, Mistral; Claude Haiku 5.5
    paid/off) with 350 ms hedging, fallthrough, Redis health circuits, stall → `Restart`; the signal
    protocol (`signal.*`, `tool.result`, `engine.incident`, `device.engine_plan`, `reply.*`,
    `tool.call`); reflex with 7 quick device tools + `delegate` stub; tier-1 stop/language; persona
    block + banned-phrase lint + tone tags; supervisor watches, heard cue, 5 s deadline sweep,
    `incidents` table + `GET /v2/incidents`; voice proxy `/v2/proxy/tts|stt` (Groq Orpheus/Whisper).
  - body (`python -m spark_body`): tier-0 grammar (338-row eval, 0 false accepts), hands (volume,
    media keys, brightness, Start Menu apps), mouth (edge-tts, Orpheus via proxy, live switching,
    circuits, text-only degrade), fitness for TTS **and STT** (hardware scan, benchmarks with a
    load-first warm-up, plan, power re-probe, EWMA, SQLite history), endpointer. **On-device voice**
    (extra `local` = sherpa-onnx): a model catalog per hardware tier (`spark_body/models.py`,
    sha256-pinned, downloads on first start with progress), wake word "hey/hi/ok spark" by
    open-vocabulary keyword spotting (no training), Moonshine-tiny STT, Piper TTS; Kokoro and
    Parakeet-0.6B only on strong PCs. Wake-gated `stt.transcribe`: audio without the phrase is
    dropped on the device; with it, STT hears only the command.
  - Electron: BodyBridge (spawn + restart), VoiceLoop relay (tier 0 first, tool calls, incidents,
    plans, trace), audio + earcons in one window, mic + VAD ear with barge-in and the wake-word gate
    (8 s follow-up window after Spark talks or a bare "Hey Spark"), **Engines** page (TTS + STT
    plan, scores, accuracy, model downloads, wake status, Run benchmark, Try it with mic).
  - evals: `brain/evals` reflex (104) + persona (58) runners (rotate keys), latency report from logs
    (per tier, `--low-spec` gate). **Scripted ear:** `body/evals/clips.py` + `SPARK_VOICE_SCRIPT`
    plays 50 "Hey Spark, …" Piper clips through the real desktop loop (TESTING §6).
  - **Speculative start** (live ear): VAD candidate at 250 ms of silence → STT (+ wake check) → the
    brain starts the reply unless tier 0 will take it (`reflex.handle decide_only`); main holds its
    live events until the 700 ms commit; resumed speech → `signal.interrupt` + merged audio heard
    again. Tier-0 speech now carries the signal id, so "what time is it" has a first-audio trace.
- **Measured on this laptop (2026-10-10):** reflex gpt-oss-20b TTFT p50 ~450–470 ms, p95
  540–820 ms across 6 runs (final: answers 50/50, tools 31/33, delegate 11/12, persona 45/56);
  Orpheus via Groq ~220 ms to first byte, ~600 ms whole sentence; Piper fp32 ~150 ms per sentence;
  edge-tts ~750 ms; Moonshine-tiny ~120 ms per command; wake check ~80 ms; real sidecar smoke:
  wake-gated command transcribed in 140–175 ms over RPC, near-misses dropped in ~85 ms.
- **Latency bench, scripted ear (2026-10-10 evening, this laptop, Nepal → Groq):** first audio p50
  1291 / p95 1621 ms over 46 utterances (low-spec gate p95 < 2000: PASS); tier 0 p50 864 ms. Spans
  p50: endpoint 704, STT 313 (+ ~80 wake check), TTFT 449, then Piper + playback. Without the
  speculative brain start: 1348 / 1732. Failover entry gpt-oss-120b TTFT 511 / 652 (20b 472 / 584).
  Barge-in: playback quiet 4–13 ms after the stop. Throttled CPU (16 busy loops): Piper p95 188 →
  1250 ms, Moonshine 125 → 391 ms, both demoted. Reflex eval after the prompt fix: answers 56/56,
  tools 32/33, delegate 11/12, persona 44/56.
- **Owner's live mic tests (2026-10-10 afternoon, Engines page, noisy room):** typed tier 0/2 work;
  "Hey Spark" is caught; after "Run benchmark" the plan is STT `groq-whisper` #1 (90% on the
  four-voice accuracy clip, ~300 ms) then `moonshine-tiny` (86%); TTS `piper` / `groq-orpheus` /
  `edge-tts` swap places by live latency. Bugs found and fixed in that session: sentences split at
  0.25 s pauses (endpoint now 0.7 s); the spotter missed bare "Spark, …" (on-device transcript
  second chance); room voices chained follow-ups forever (now 2 follow-ups within 6 s after a
  "Hey Spark" request); follow-ups never worked because audio plays in the floating panel while the
  ear runs in the main window (speaking state now broadcast to every window); Whisper's "foreign"
  noise hallucination; "what time it is" delegated (tier 0 + prompt fix).
- **R2 done, pending the owner's smoke test,** on branch `r2/agent-loop` (from `main` at `725268a`). Plan shown to the owner
  2026-10-10: M1 contracts → M2 agent + jobs → M3 desktop hands → M4 cross-device → M5 agent eval →
  M6 UI (mockups first, owner reviews) → M7 delete v1 executor + close. **M1 + M2 done:**
  `ToolSpec` v2 (output model, `match` field for rules, review flag, confirm text, MCP annotations,
  brain-tool `handler`), 25 agent device tool specs + 5 brain tools, `tools/registry.py` (keyword
  pre-selector, 8 picks + `file_list`/`file_read`, `tool_search` for more), agent/subagent/review
  chains (Groq gpt-oss-120b → qwen3.8-27b → gpt-oss-20b, then keyless entries), migration 0003
  (jobs, job_steps, approvals, artifacts, queued_actions, permission_rules), `agent/loop.py`,
  `jobs/runtime.py`, permission engine + auto-reviewer + hooks (redaction, audit), grounding check,
  approvals on every device (first answer wins), `ask_user`, `task` sub-agents, `plan_submit`,
  tier 1 status / yes-no-always / ask answers, `signal.interrupt {scope: all}`, reflex `job_steer` /
  `job_cancel`, routes `/v2/jobs`, `/v2/permissions/rules`, `/v2/capabilities/tools`. Brain: 124 tests
  (37 new), ruff + mypy clean. **M3 done:** `body/spark_body/hands/` files.py (known folders via
  SHGetKnownFolderPath, so OneDrive Desktop/Documents resolve; system-folder + known-folder guards;
  Recycle Bin deletes with a last-part glob; organize + restore via a hidden manifest), shell.py,
  desktop.py (clipboard + screenshot via PowerShell, SendInput keyboard/mouse, tasklist/taskkill,
  system info, lock, sleep); `hands.CAPABILITIES` in `hello`; body 79 tests (19 new). Electron:
  `brain.approve/answer/cancelJob/jobs` IPC, `brainAuth.request`, tier-0 "stop" sends
  `scope: "all"`. **M4 done:** `agent/targets.py` (explicit name/kind/default → origin →
  capable online device, said aloud; two matches → ask, the answer becomes the default; offline →
  offer → "yes" → `queued_actions`, fired on the device's next hello, 1 h), optional `device` on
  device tools when the user has several, tier 1 remote commands / "send this to my phone" /
  "continue on my phone", wake arbitration (`gateway/wake.py`, Redis window, yielded devices and
  repeated words dropped), `/v2/uploads`, `/v2/artifacts/{id}` (+ signed download, no token),
  `/v2/threads`, S3 re-route; Electron claims the wake word before acting. Brain 139 tests.
  Evals after the reflex prompt change (2026-10-10): gpt-oss-20b answers 59/59, tools 32/33,
  delegate 11/12, persona 49/56, TTFT p50 476 / p95 620 ms; 120b 59/59, 32/33, 11/12, 51/56.
  **M5 done:** `brain/evals/agent.py` + 30 tasks (stubbed tools, unlisted lookups find nothing):
  gpt-oss-120b 22/30, gpt-oss-20b 23/30, qwen3.8-27b 21/30 (4 rate-limited), every call valid;
  misses are flaky run to run, so the chain order stays 120b → qwen → 20b. Fixes from it: tool
  picker weights name > keywords > description and down-weights words naming many tools ("file");
  "stop after 2–3 empty searches" prompt line; grounding ignores unicode hyphens/quotes; whitespace-
  only model replies are a bad turn in the agent and a spoken "lost track" line in the reflex (S9);
  `GET /v2/engines/chains` for Engines → Models. Reflex eval after: 20b answers 59/59, tools 31/33,
  delegate 11/12, TTFT p50 481 / p95 607 ms; 120b 59/59, 30/33, 11/12. Brain 144 tests.
  **Voice overlay redone (owner, 2026-10-10, with a screen recording of the old pill jumping):**
  the floating window (`/ai-panel`) is now Spark's main voice surface, a notch hanging from the top
  edge of the screen (flat top, concave flares, rounded bottom): it shows what you said and Spark's
  reply live, the running job, approvals and questions, and the orb glows with Spark's real voice
  level (and the mic's while listening). The window is fixed at 640×480, transparent and
  click-through except over the notch (`overlayInteractive`); only the notch morphs (motion
  springs, measured height), so nothing jumps or clips. The ear now lives in the overlay, mic off
  at start (button or Ctrl+Shift+M). v1 `pages/AiPanel/` deleted. `sparkSlice` registered; every
  window folds every brain event. Electron vitest: 10 tests.
  **M6 main window done:** `pages/Home.tsx` is the new shell (rail: Home · Activity ·
  Capabilities · Engines · Settings, Ctrl+K palette, frameless header with the mic toggle);
  `pages/spark/` HomePage (conversation, inline approval/question cards shared with the overlay,
  input bar, live job panel with Stop), ActivityPage (jobs + step log, incidents), CapabilitiesPage
  (search, three-way permission control writing bare rules), EnginesHub (Voice = the old Engines
  page minus its test chat and second ear, Models = `/v2/engines/chains`), SettingsHub (account,
  devices, permission mode + rules, verbosity / name / training toggle). Main sends every user
  line to all windows (`voiceUserSaid`); the overlay's ear state and toggle go through main
  (`voiceEarSet/Get/Toggle`). Bug found in the browser check: `useEffect(() => el.scrollIntoView())`
  returned a Promise (new Chromium) as the cleanup and crashed React on unmount. Electron tests 21
  (vitest + Testing Library). The v1 pages under `pages/home/` and `components/local/home/` are now
  unused; `HomeLive.tsx` holds the owner's uncommitted edits, so it stays until they say.
  **Can't-do prompts (2026-10-10):** the reflex delegated impossible asks ("what's my bank
  balance", "call my mom") once delegate started real jobs, and every agent model asked questions
  instead of saying it can't book a table. Both prompts now say so first. After: persona 20b 46/56
  (was 42), 120b 53/56 (was 49); reflex 20b 59/59, 31/33, 11/12; 120b 59/59, 32/33, 10/12 (a
  "write a cover letter and save it" answered inline: variance near the line); agent 120b 24/30
  (was 22), 20b 27/30 (was 23), can't-do passes on both. Over three runs the two are about even
  (120b 21/22/24, 20b 18/23/27), so the agent chain keeps 120b first.
  **M7 done (2026-10-11, owner: "unused can be deleted"):** import-graph walk from the three
  entry points, then deleted what nothing reached: v1 pages (incl. `HomeLive.tsx`), bottom bar,
  device widgets, terminals, UI-kit pieces, v1 hooks, the v1 socket + TTS contexts, the executor
  (`ActionExecutorService.ts`, never started: `startActionExecutor` had no caller), `SocketService`
  + `TokenManager`, device-usage polling (pushed CPU/RAM to no listener), unused IPC
  (`getFrameState`, `setOnboardingWindowMode`, `showOpenFileDialog`, `openSecondaryWindow`,
  media/system permission getters), `electron/action_executor/` + `electron/python-service/`
  (105 files), v1 socket/agentic types, 13 npm packages (+2 `@types`). Renderer build 18 s → 12 s.
  Brain container rebuilt (migration 0003 at head). Still v1 and broken: Onboarding saves the
  user's details through `axios` to the v1 server (`/auth/update-user-details`); port it to
  `PATCH /v2/settings` (R3 or sooner). R2 boxes in PHASES ticked.
  **NEXT:** the owner's R2 smoke test (`TESTING.md` §8c; Spark talks), then push R2 to main and
  start R3. Open voice items, only if they show up in use: a
  loudness gate for follow-ups in noisy rooms, speaker-aware barge-in, the on-device wake cut (FT10
  flaky). Cleanup for later: `electron/.env` (v1, two URLs, no secrets) is still tracked in git.
- **R3 Memory started** 2026-10-11 on branch `r3/memory` (from `r2/agent-loop`; R2 still waits
  for the owner's smoke test, so R3 isn't on main either). **M1 brain memory done:** migration 0004
  (`memories`, halfvec(384) + HNSW + generated tsvector + GIN), `brain/app/memory/` (embed.py:
  multilingual-e5-small int8 ONNX, downloaded on the brain's first start into `MODELS_DIR`,
  sha256-pinned; store.py: save with dedupe, hybrid search fused by reciprocal rank, profile,
  forget, decay; extract.py: background extraction after reflex turns on a new `memory` chain role;
  tools.py: remember / recall / forget), reflex prompt gets the profile (system, cacheable) and
  found memories (volatile note), remember/forget run in the reflex, the agent gets all three,
  `/v2/memories` routes, prompt-cache hits per role in `GET /v2/engines/chains`. Brain 161 tests
  (+16 M rows, +1 real-model test). Retrieval at 10k memories/user: p50 ~16, p95 18–22 ms.
- **Running the stack:** `docker compose -f deploy/docker-compose.yml up -d --build brain` (rebuild
  after brain changes), `cd electron && npm run dev` (spawns the body from `body/.venv`; restart it
  after body or main-process changes; renderer changes hot-reload). The body logs one line per
  utterance (`ear: 2.3 s of speech, wake=True, groq-whisper in 297 ms, 6 words`, never the words).
  The v1 Chat/Activity pages and the floating panel's chat are v1 (server off); test R1 on Engines.
- **This laptop:** 8 cores, 7.4 GB RAM, AMD (no CUDA): local LLMs must be small (R5 Models page).
- **Deferred past R0:** per-user rate limits, `sync.resume`/X4, retention jobs, real Caddy config,
  Electron lint warnings (react-hooks exhaustive-deps).
- **Run locally:** `docker compose -f deploy/docker-compose.yml up -d` (brain on :8080; secrets in
  git-ignored `deploy/.env`). Tests: `docker compose -f deploy/docker-compose.test.yml up -d`, then
  `cd brain && uv run pytest`. Desktop: `cd electron && npm run dev`. uv lives in
  `%APPDATA%/Python/Python311/Scripts` (not on PATH, PowerShell included). Voice models live in
  `%LOCALAPPDATA%/SparkAI/models` (v1's `embedding/`, `emotion/`, `whisper/` folders there are v1's).
- **Working tree:** the owner's uncommitted v1 edits (`server/*`, `README.md`, `scripts/`,
  `*.env.example`) are theirs. Never stage them. (`HomeLive.tsx` and `ActionExecutorService.ts`
  were deleted in M7 with the owner's OK.)
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

**Owner decisions (2026-10-10, morning)**
- First-audio target: 1 s, or **2 s on low-spec devices** (this laptop). Implemented as a 700 ms TTS
  budget on hardware tier 0 (250 ms elsewhere), so the expressive Orpheus voice can lead here.
- Local models load **automatically per device** on the client side: the body picks by hardware
  tier, downloads, benchmarks, and keeps what fits. No manual model choice.
- No wake-word training: the wake word must be free and train-free (hence keyword spotting).
- RA3, RA4, PS3 move to R2 (they need jobs and approvals).
- The Groq keys from v1's `server/.env` are the ones to use (Orpheus terms accepted).
- The agent owns the codebase decisions ("the codebase is yours").

**R1 implementation choices (2026-10-10, agent; owner can overrule)**
- Body ↔ Electron framing is NDJSON (one JSON-RPC object per line), not Content-Length frames.
- Audio is synthesized in the body and played in the renderer (Chromium decodes MP3/WAV; no Python
  audio decoder). Whole-sentence blobs for now; MediaSource streaming if first audio needs it.
- The R1 ear runs mic + Silero VAD in the renderer (`vad-web`, already a v1 dependency) with
  Chromium echo cancellation; STT engine choice stays in the body. The wake word is checked in the
  body per endpointed utterance (not on a continuous stream): no second mic capture, and "Hey Spark,
  do X" in one breath works. A continuous body-side ear can replace it if latency demands.
- Wake word = sherpa-onnx keyword spotter (gigaspeech 3.3M, fp32), phrases as BPE tokens in
  `ear/wake.py`. Knobs to tune on real voices: `THRESHOLD` 0.25, `LOOKBACK_S` 0.4 (where the
  command starts: the spotter fires ~0.4 s after the phrase ends).
- Model catalog picks fp32 over int8 (4x faster on CPUs without VNNI, measured). Piper voice is
  LibriTTS-R (CC-BY-4.0 data) over Ryan (CC BY-NC-SA data). Pocket TTS skipped (2 s here and its
  README says non-commercial while the LICENSE says CC-BY-4.0), Kitten/Parakeet-110M lost on
  speed/accuracy.
- Engines that miss the budget stay in the plan after the ones that fit, as last-resort fallbacks;
  the quick check doesn't spend probes (or Orpheus quota) on them.
- Local engines serialize native calls with a thread lock taken on the worker thread (all local
  voices share one: espeak-ng is global).
- Live events (`reply.delta`, `reply.cue`, `tool.call`, `tool.cancel`) go only to the origin device
  and skip the sync log; the thread history holds the outcome. A turn is stored before its final
  marker, so a follow-up always sees it.
- If no TTS engine fits the 250 ms budget, the working ones stay in the plan (fastest first) instead
  of going mute; the heard cue covers the gap.
- Tier 0 is grammar-only (full match + every slot resolved + app in the installed index); the
  embedding classifier waits for its ONNX model.
- Speculative start lives in Electron main (`VoiceLoop.hear` / `commit` / `drop`), not the brain:
  the brain only sees an early `signal.final` and, rarely, a `signal.interrupt`. Tier-0 commands
  are never speculated (side effects); they run at commit.
- Cloud STT hears the whole utterance; only on-device STT gets the wake cut (the cut is ±0.1 s and
  took first words; Whisper copes with "Hey Spark" and `strip_wake` removes it).
- The scripted ear is a dev env var in Electron main, not a separate driver: it measures the real
  path including playback, and its traces land in the brain log like live ones.

**R3 implementation choices (2026-10-11, agent; owner can overrule)**
- Embedder: multilingual-e5-small, **int8** ONNX (118 MB + 17 MB tokenizer). On this laptop int8 is
  faster than fp32 (5.5 vs 10.6 ms p50 per short line) with the same ranking. 384-d, multilingual
  so memories stay language-neutral. New brain deps: `onnxruntime` + `tokenizers` (run it) and
  `numpy` (pooling); `tokenizers` pulls `huggingface-hub` transitively (unused by our code: the
  download is 20 lines of httpx with a pinned revision + sha256).
- Embeddings are `halfvec(384)`: half the row of `vector`, same ranking; the full-text arm reads
  every matching row, so smaller rows kept retrieval under budget at 10k memories.
- Thresholds measured on e5: related query/memory 0.79–0.84, unrelated 0.71–0.78 → the prompt
  gets vector hits ≥ 0.77; a paraphrase is 0.96–0.99 but so is "dark mode" vs "light mode" (0.96)
  and two sisters are 0.92 → near-duplicates merge at ≥ 0.95 (newest wording wins); real
  corrections come from the extractor's `replaces` (it sees the 5 nearest known memories).
- No `profiles` table: the profile is the most important live memories (≤ 1200 chars), rebuilt
  on any change, cached in Redis. An LLM summary could keep a forgotten fact; this can't. Add an
  LLM summary only if users pile up hundreds of memories and the top-N cut loses too much.
- Extraction mines only the user's words (+ Spark's reply for context), never tool output, and
  only lines in the first person (no call for "volume to 30"). Memories the agent saves during a
  job are unconfirmed until the user OKs them on the Memory page (injection guard, §21).
- Forget deletes the row; the old line can still sit in the current thread's recent history (it's
  conversation, not memory) until the thread goes idle.
- `hnsw.iterative_scan = strict_order` and nothing else is set per DB connection (asyncpg
  `server_settings`), so the shared HNSW index fills a user's LIMIT in exact order.
- JWT `iat` is no longer checked against wall time (exp already is, against the injected clock):
  tests that moved the fake clock past real time were refused at sign-in.

**R2 implementation choices (2026-10-10, agent; owner can overrule)**
- Phone in R2 = a mobile body (FakeDevice); ADB sub-device routing (`adb:<serial>` via the laptop)
  comes with real ADB in R4. D1 runs on stub Gmail brain tools; T5 tests only the MCP permission
  rule (the MCP client comes later).
- Running jobs fail cleanly on a brain restart (`fail_stale`), they don't resume. Tool, approval,
  and ask futures stay in-process (one brain process until R7); approval decisions are atomic in
  Postgres (`WHERE decision IS NULL`).
- The agent doesn't speak its steps: acks, approvals, questions, "taking longer" notes, and the
  wrap-up (≤ 3 sentences; the rest becomes a `text` artifact). Job speech reuses `reply.delta` on
  the origin signal id, one `final` marker per utterance.
- "Medium risk" = write tools flagged `review` (file write/edit/move, organize, keyboard, mouse,
  app close, sleep): the auto-reviewer (review chain, one word ALLOW/ASK) decides in default mode;
  any error asks. `shell_run` is destructive except a small read-only allowlist (no chaining,
  pipes, redirects, subexpressions). `file_delete` goes to the Recycle Bin and takes a glob in the
  last part ("Downloads/*" = one approval for the whole folder).
- Two malformed turns in a row (unparseable or unknown tool, Groq 400 `tool_use_failed`, or a
  schema-invalid input) exclude that chain entry for the rest of the job. Malformed doesn't open
  the provider's circuit (the reflex keeps using it).
- Grounding is a shape heuristic (quoted text, file names, times, ids, capitalized mid-sentence
  names must appear in the user's words or a tool input/output); one rewrite, then a safe line.
- Plan approval grants only exact targets for that job; "always" stores a glob-escaped exact rule.
- Artifacts: bytes under `ARTIFACTS_DIR` (compose volume), HMAC-signed download URLs (1 h).
- Desktop unit tests use vitest (dev dependency, 2026-10-10): reducers and pure UI logic first;
  Testing Library and Playwright for Electron come with M6 component and E2E tests.
- The ear runs in the overlay window, not the main window: the overlay is always there (main can be
  hidden to the tray) and audio already plays there. The Engines page's own mic toggle is a second
  ear; don't run both at once (M6 points it at the overlay's).

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
- **edge-tts misses the budget here** (p50 ~740 ms, p95 up to ~1.8 s): it's a fallback only;
  Orpheus (cloud) leads under the 700 ms low-spec budget, Piper (local, ~150 ms) follows.
- **Wake word and its cut were tuned on synthetic voices** (Piper, 3 speakers): 11/12 caught, 0/15
  false alarms. Real mics, accents, and noise may need `THRESHOLD` / `LOOKBACK_S` changes.
- **Moonshine-tiny on accented English** is unmeasured (the probe clip is synthetic US English);
  Groq Whisper stays as the STT fallback. Non-English speech needs Whisper (local models are English).
- **Orpheus quota:** ~100 clips/day per key; a reply is 2–3 clips. 8 keys cover one heavy user.
- **The Mistral key from v1 is out of quota** (429 on every call) and Cloudflare has no key: the
  reflex chain is effectively Groq-only until more keys are added.
- **Delegate vs answer is a prompt balance:** "never say you can't, delegate" sent "drive my car" to
  delegate; the current wording keeps chit-chat local but still delegates some predictions ("stock
  market tomorrow") and explains at length (> 3 sentences) on "how does X work". Results vary run
  to run by a few rows. Re-run both evals after prompt edits.
- The tier-0 eval set was written alongside the grammar (0 false accepts is partly self-graded);
  add real transcripts from use before trusting the < 0.5% number.
- Hedge is adaptive since 2026-10-10 (1.3 x the entry's usual TTFT, 350 ms floor): from Nepal it
  waits ~600 ms instead of firing on ~95% of calls. Key use is failover-only: key 1 leads, key 2
  takes the hedge, keys 3–8 only after 429s.
- httpx's 5 s keep-alive doesn't cost a handshake per turn: measured the same first-token times
  with a 300 s keep-alive (Groq's edge is near).
- Speculative start spends an LLM call (2 with the hedge) whenever speech resumes after a 250 ms
  pause; add a minimum utterance length before speculating if daily limits bite.
- Wake word on Piper voices: 47/50 caught (3 "He sparked …" missed by both the spotter and the
  on-device second chance). FT10 (real models) is flaky ~1 run in 6 for the same cut reason.
- gpt-oss-120b (the failover) once answered "I'll draft it and save it" without delegating.
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
| 2026-10-10 | Reflex eval: 45/95 rate-limited (one key, 8K tokens/min) | The runner rotates all keys like the chain runner |
| 2026-10-10 | sherpa-onnx failed with "API version 28 not available, ORT 1.17.1": `uv.lock` dropped `sherpa-onnx-core` on Windows, so System32's old `onnxruntime.dll` loaded | List `sherpa-onnx-core` in the `local` extra, versions pinned equal |
| 2026-10-10 | Kokoro download failed its checksum: upstream re-uploaded it and `checksum.txt` was stale | Pin GitHub's per-asset `digest` instead |
| 2026-10-10 | Local engines benchmarked at ~1.5 s p95: the first call includes model load | `warm()` (load + one run) before timing; the ear warms at start |
| 2026-10-10 | Sidecar stalled: a probe timed out while a model was loading, and a second load raced it in another thread | Thread lock taken on the worker thread (asyncio locks release on cancel while native work runs on) |
| 2026-10-10 | Moonshine heard "Hey Spark, turn the volume…" as "He sparked her in the volume…" | Cut the audio where the spotter fired minus 0.4 s; STT hears only the command |
| 2026-10-10 | Mic test: long requests arrived as fragments; only the first got through | VAD endpoint 0.25 s → 0.7 s of silence |
| 2026-10-10 | Mic test: strangers' lines answered 6–8 times in a row after one "Hey Spark" | Follow-ups capped at 2, each within 6 s of Spark finishing; barge-in only inside an exchange |
| 2026-10-10 | Mic test: follow-ups always needed "Hey Spark" | Audio plays in the floating panel, the ear ran in the main window, speaking state was per window: broadcast via main (`voiceSpeakingState`) |
| 2026-10-10 | Whisper turned room noise into "foreign" and Spark answered it | Drop whole-transcript Whisper hallucinations |
| 2026-10-10 | Floating pill jumped sideways and clipped its icons on hover (owner's recording) | It resized and re-centred the OS window per hover; now a fixed click-through window with the notch morphing in CSS |
| 2026-10-10 | Agent eval: gpt-oss sometimes answers with nothing; a whitespace-only reply ended a job "done" in silence | Bad turn in the agent loop (retry, then next entry); the reflex says a "lost track" line |
| 2026-10-10 | Tool picker missed clipboard tools for "save my clipboard to a file" ("file" named eight tools) | Words that name many tools count less |
| 2026-10-10 | Tier-0 answers ("what time is it") never reported first audio: spoken as `t0-<intent>`, not the signal id | `reflex.handle { utt_id: "<signal_id>:t0" }` |
| 2026-10-10 | Bench: the wake cut took the command's first word ("what time is it" → "I miss it") | Cloud STT hears the whole utterance; only on-device STT gets the cut |
| 2026-10-10 | Bench: Whisper's "Hayspark turned the volume up" escaped tier 0, and the reflex said "volume's up" without calling the tool | `strip_wake` / tier-0 filler take joined forms; a leading "turned" reads as "turn"; RA1 rows |
| 2026-10-10 | Bench: the reflex delegated plain facts ("how far is the moon", "speed of light", "recommend a book") → "I can't run multi-step jobs yet" | Prompt: "just answer" first with examples, delegate only for what one reply can't know or do; 6 eval rows |
| 2026-10-10 | Mic test: "yes, do it" after Spark asked a question was dropped ("no wake phrase") | One answer needs no wake word when Spark ended on a question (`asked` in `voiceSpeakingState`); VAD `minSpeechMs` 300 → 200 |
| 2026-10-10 | Mic test: transcripts turned bad ("I'm sparked… the bossy is of"): one 1.2 s Whisper call of three put its p95 over budget, Moonshine led, and nothing re-probed Whisper | Warm-up call for cloud engines, a start-up probe for engines whose median fits, benchmarks behind one lock (FT12) |
| 2026-10-10 | "Can you tell me the percentage of battery?" → "I can't run multi-step jobs yet" | Tier-0 `battery_status` (`GetSystemPowerStatus`) |
| 2026-10-10 | Mic test: talking over Spark didn't stop it once the 2 follow-ups were used; "Hey Spark, wait" wasn't a stop word | Barge-in always (0.2 s of real speech outside an exchange, first frames inside), the interrupting line needs no wake word; "wait" / "hold on" are tier-0 stop |
| 2026-10-10 | Mic test: first tries ignored: the spotter missed and Moonshine's second chance heard "I'm sparked" / "He sparked" | Second chance and the stripper accept he / his / I'm + spark(ed) |
| 2026-10-10 | Mic test: "Okay, okay", "Nerd, nerd" → "I can't run multi-step jobs yet" five times; its question let the next fragment in without the wake word | Reflex: fragments get "didn't catch that", never delegate (eval rows); at most 4 lines in a row skip the wake word |
| 2026-10-10 | Vite `EACCES` on :5123 after Docker started | Windows dynamic port range started at 1024, so Hyper-V reserved 5041–5140; reset to 49152+ (`netsh int ipv4/ipv6 set dynamic tcp start=49152 num=16384`) + restart `winnat` |
