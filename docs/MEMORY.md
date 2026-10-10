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
- **R1 built, every PHASES box ticked** (2026-10-10, evening) on local branch `r1/voice-loop` (not
  pushed). Brain 86 tests (incl. 100-signal chaos), body 59 (Windows CI job; 2 real-model tests run
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
  - evals: `brain/evals` reflex (101) + persona (58) runners (rotate keys), latency report from logs
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
- **NEXT (start here):** the owner's mic smoke of the new ear (TESTING §8b step 6): "Hey Spark,
  tell me a joke" → "another one" → "one more" (no wake word) → a 4th without it is ignored; a long
  request with a short pause mid-sentence arrives whole. If room voices still slip into follow-ups,
  add a loudness gate (a follow-up only if about as loud as the "Hey Spark" utterance). Then the
  owner fast-forwards `r1/voice-loop` onto `origin/main` and R2 starts. Open owner calls: the hedge
  delay (below) and whether low-spec p50 must also be < 1 s (read here as p95 < 2 s, as written).
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
- **Hedging at 350 ms fires on ~95% of reflex calls** from Nepal (TTFT ~450–480 ms): every turn
  costs 2 Groq requests. A hedge at ~600 ms (about p95) would halve that and still catch outliers;
  owner's call (the 350 ms is a design decision). Key use is failover-only: key 1 leads, key 2
  takes the hedge, keys 3–8 only after 429s.
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
| 2026-10-10 | Tier-0 answers ("what time is it") never reported first audio: spoken as `t0-<intent>`, not the signal id | `reflex.handle { utt_id: "<signal_id>:t0" }` |
| 2026-10-10 | Bench: the wake cut took the command's first word ("what time is it" → "I miss it") | Cloud STT hears the whole utterance; only on-device STT gets the cut |
| 2026-10-10 | Bench: Whisper's "Hayspark turned the volume up" escaped tier 0, and the reflex said "volume's up" without calling the tool | `strip_wake` / tier-0 filler take joined forms; a leading "turned" reads as "turn"; RA1 rows |
| 2026-10-10 | Bench: the reflex delegated plain facts ("how far is the moon", "speed of light", "recommend a book") → "I can't run multi-step jobs yet" | Prompt: "just answer" first with examples, delegate only for what one reply can't know or do; 6 eval rows |
| 2026-10-10 | Vite `EACCES` on :5123 after Docker started | Windows dynamic port range started at 1024, so Hyper-V reserved 5041–5140; reset to 49152+ (`netsh int ipv4/ipv6 set dynamic tcp start=49152 num=16384`) + restart `winnat` |
