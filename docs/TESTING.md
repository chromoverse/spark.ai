# TESTING.md — v2 Testing Strategy

**Rule: every scenario in `REDESIGN.md` has an automated test.** A flow, remedy, or guarantee
without a test isn't done. Each test names the section it proves (e.g. `# proves §26.4-E`).

---

## 1. Principles

1. **Test the promise, not the plumbing.** "Every signal ends answered or explained" is tested by
   firing signals under failure. Unit tests alone don't prove it.
2. **No real network in CI.** LLM, STT, TTS, OAuth, and search providers are replaced by scriptable
   fakes. Live checks run separately (§7) and never gate a merge.
3. **Latency is asserted.** Simulated clocks verify the budget math; the latency bench (§6) measures
   the real thing.
4. **Simulated bodies.** Cross-device flows run with in-process fake devices that speak the real
   gateway protocol (§9).
5. **Free-only in CI.** No test may need a paid provider (`PAID_PROVIDERS_ENABLED=false`).

## 2. Test Harness (built in R0, extended every phase)

| Component | What it is | Lives in |
|---|---|---|
| ✅ `FakeProvider` | OpenAI-compatible fake LLM: scripted text/tool-call streams, configurable time-to-first-token, gaps, 429s, 5xx, empty output, malformed tool calls | `brain/tests/fakes/llm.py` |
| ✅ `FakeDevice` | in-process Socket.IO client speaking protocol v2: `device.hello`, `say()` → `signal.final`, `reply()` collects a turn's `reply.delta`s, auto-answers `tool.call` from `tools` (optional `before_result` delay on the fake clock). Wake claims and offline toggling come with R2 | `brain/tests/fakes/device.py` |
| ✅ `FakeEngines` | TTS fakes with scripted latency, empty audio, 503s, hangs, and an installed flag (STT fakes join with the ear) | `body/tests/fakes/engines.py` |
| `FakeOAuth` / `FakeGoogle` | ✅ R0: Google sign-in (authorize + token endpoint). Later: Gmail/Calendar/Drive fakes with fixtures; expired/revoked token modes | `brain/tests/fakes/google.py` |
| ✅ `Clock` (`FakeClock`) | controllable time for deadlines, hedging, cooldowns. `drive(clock, aw)` moves simulated time while awaiting; `until(pred)` waits for server-side state | `brain/tests/fakes/clock.py` |
| `Chaos` | injects provider failures, latency spikes, device drops, empty outputs at a set rate | `brain/tests/chaos.py` |
| ✅ Test DB | Postgres + pgvector + Redis via `docker compose -f deploy/docker-compose.test.yml` | CI service containers |
| ✅ `FakeResend` / `FakeHttp` | OTP mail capture + outage mode; `FakeHttp` routes the brain's shared httpx client to fakes by host and fails on any unexpected outbound call | `brain/tests/fakes/resend.py`, `brain/tests/conftest.py` |

The `brain` fixture runs the real app under uvicorn on a random port (HTTP + Socket.IO), drops the
test schema and runs `alembic upgrade head` once per session, and truncates tables + flushes Redis
before each test. Tests that need it fail (they don't skip) when the test stack isn't up.

## 3. Commands

```bash
# brain
docker compose -f deploy/docker-compose.test.yml up -d   # Postgres :55432 + Redis :56379
cd brain && uv run pytest -q                 # unit + integration (fakes, test DB)
cd brain && uv run ruff check . && uv run mypy app
cd brain && uv run pytest -q -m scenario     # scenario suite (§4)
cd brain && uv run pytest -q -m chaos        # chaos suite (§5, from R1)
# body (spark-body sidecar)
cd body && uv sync && uv run pytest -q   # + ruff check, mypy spark_body (CI on windows-latest)
cd body && python -m spark_body.fitness --bench   # real hardware benchmark (manual / nightly)
# desktop
cd electron && npm run lint && npm run typecheck   # what CI runs
cd electron && npm test && npm run e2e             # unit/component + Playwright vs fake brain (not built yet)
# evals (live free providers, never in PR CI)
cd brain && uv run python -m evals.run --suite reflex   # ✅ R1: 95 utterances, every keyed reflex entry
cd brain && uv run python -m evals.latency < brain.log  # ✅ R1: p50/p95 first audio from signal traces
cd body && uv run pytest tests/test_reflex_arc.py      # ✅ reflex_arc suite (offline, in CI)
```

## 4. Scenario Matrix (every row is an automated test)

### 4.1 Request flows (`REDESIGN.md` §26)
| ID | Scenario | Assertions |
|---|---|---|
| A1 | "volume to 30" (tier-0 reflex arc) | no LLM call made; device tool ran; `signal.handled_locally` stored in the thread; chime event; ≤ 300 ms simulated. ✅ brain half `test_a1_tier0_result_is_recorded_without_an_llm`, device half `body/tests/test_body.py::test_a1_device_half_volume_runs_locally_with_a_chime` (latency is real-time on the device: measured by the bench) |
| A2 ✅ | near-miss "play a song that fits my mood" | reflex arc does **not** accept; goes to the reflex LLM. `body/tests/test_body.py::test_not_sure_goes_to_the_brain` + 80 near-miss rows in RA1; the brain side is B1 |
| A3 ✅ | tier-0 action fails (app not installed) | escalates to the reflex LLM with the error; spoken alternative offered. `test_a3_tier0_failure_escalates_to_the_reflex` |
| B1 ✅ | normal conversation | reflex LLM called once; `reply.delta` streamed per sentence; first delta within budget given fake TTFT 300 ms. `test_b1_*` (+ recent turns carried into the follow-up) |
| B2 ✅ | first provider slow (TTFT 600 ms) | hedge fires at 350 ms; second provider's stream used; first cancelled. `brain/tests/test_llm_chains.py::test_b2_hedge_at_350ms_second_stream_wins` |
| C1 ✅ | "open Spotify and play something calm" | speech delta and `tool.call` emitted in the same turn (parallel); done chime on success. `test_c1_*`: chime ≤ 1.5 s, spoken "Done." when slower, explained failure with a next step |
| D1 | invoice email → save PDF | agent loop: gmail_search → get_attachment → file_write on the origin device; job steps persisted; summary contains only items from tool outputs |
| D2 | D1 with Gmail not connected | connect card emitted; job paused; after fake OAuth completes, job resumes without a new signal |
| E1 | spoken to laptop: "open YouTube on my phone" | target resolved to `adb:<serial>`; tool runs on the phone sub-device; the laptop speaks the ack before the tool result |
| E2 | E1 with the phone offline | spoken explanation + offer to queue; queued run fires when the phone comes online; expires after 1 h |
| E3 | two phones, "on my phone" | asks once; the answer is saved as default; the next request doesn't ask |
| E4 | capability fallback: "send an SMS" from the laptop | routed to the phone with an announcement |
| F1 | spoken to the phone: "pause music on my laptop" | brain routes with no LLM; the laptop gets `tool.call` |
| G1 | handoff "send this to my phone" | artifact uploaded; phone notified; download URL valid and signed |
| G2 | "continue on my phone" | both devices see the same thread state after sync |

### 4.2 Wake-word arbitration (§26.2)
| ID | Scenario | Assertions |
|---|---|---|
| W1 | two devices claim within 150 ms | exactly one `wake.grant`; others `wake.yield`; the winner has the higher score + loudness |
| W2 | tie | the foreground / most recently used device wins |
| W3 | a claim after the window | treated as a new signal only if its text differs; otherwise deduplicated |

### 4.3 Reflex arc (§27)
| ID | Scenario | Assertions |
|---|---|---|
| RA1 ✅ | eval set of ~300 utterances (positives, near-misses, negatives) | false-accept rate < 0.5%; per-intent slot accuracy ≥ 98%. `body/evals/reflex_arc.jsonl` (338 rows) via `body/tests/test_reflex_arc.py`: 0 false accepts, 100% slots. Grammar only for now; the embedding classifier joins when the ONNX model ships |
| RA2 ✅ | destructive / send / purchase phrasing | never accepted by tier 0 (30 `never` rows) |
| RA3 | tier 1: "how's it going" during a job | answered from job state; no LLM call |
| RA4 | tier 1: "yes do it" with a pending approval | resolves the approval; no LLM call |

### 4.4 Device fitness & engines (§18)
| ID | Scenario | Assertions |
|---|---|---|
| FT1 ✅ | full benchmark with fake engines (one fast, one slow) | the slow engine is excluded; the plan is ordered by expressiveness then latency. `body/tests/test_mouth_fitness.py` (+ nothing fits → working engines stay, fastest first) |
| FT2 ✅ | quick check on start | completes ≤ 2 s; plan unchanged when scores are stable |
| FT3 ✅ | power change (battery saver) | affected roles re-probed; plan updated; the plan survives a restart |
| FT4 ✅ | selected TTS returns empty audio twice | switches to the next engine for the same sentence; incident logged |
| FT5 ✅ | tone tags | kept for Orpheus, stripped for engines without vocal-direction support |
| FT6 ✅ | edge-tts 503 | circuit opens for 10 min; fallback engine used; Engines page reason text set |

### 4.5 Supervisor — never silent (§19)
| ID | Scenario | Assertions |
|---|---|---|
| S1 ✅ | stalled LLM stream (gap > 1.5 s) | switch to the next provider; the user hears a bridge cue. `test_s1_stalled_stream_bridges_then_next_provider_answers` + `test_llm_chains.py::test_s1_*` |
| S2 | tool times out | agent gets a tool error and re-plans; job doesn't hang |
| S3 | target device sleeps mid-job | re-route to another capable device, or explain |
| S4 | identical tool call 3× | loop broken; agent told; job ends explained |
| S5 | grounding: summary names an event absent from tool output | blocked before speaking; regenerated or corrected (v1 calendar bug) |
| S6 ✅ | Groq quota exhausted | next chain entry used; health marks Groq cooling down until reset. `test_llm_chains.py::test_s6_rate_limit_falls_through_and_cools_down`; all entries down → `test_every_provider_down_is_explained_never_silent` |
| S7 | estimate miss (job 2× over estimate) | user gets a progress note with a new estimate |
| S8 ✅ | invariant sweep | any signal past its deadline without a terminal state triggers the playbook. `test_s8_signal_past_its_deadline_is_explained` |

### 4.6 Agent, tools, permissions (§5.2, §7, §20)
| ID | Scenario | Assertions |
|---|---|---|
| T1 | parallel read tools | all tool_results returned in **one** user message; ran concurrently |
| T2 | malformed tool call twice | escalates to the next chain entry; history preserved |
| T3 | deny → ask → allow precedence | a broad deny beats a narrow allow; a bare-tool deny removes the tool from the model's tool list |
| T4 | auto-reviewer | medium-risk call matching the request is allowed; a mismatch escalates to ask |
| T5 | MCP untrusted server with `readOnlyHint` | still treated as "ask" |
| T6 | output over 25k tokens | stored as an artifact; the model gets a preview + handle |
| T7 | skill import | a skill folder from Claude Code / Codex loads; only name + description enter context until used |
| T8 | workflow mode | intermediate rows never appear in model messages; the final artifact is correct |
| T9 | v1 bug regression: Gmail ids | a bad binding (`step_1.maps_link`) is rejected by schema validation before any API call |

### 4.7 Identity, security, sync (§12, §10)
| ID | Scenario | Assertions |
|---|---|---|
| X1 ✅ | every HTTP route and socket event | rejects client-supplied `user_id`; user A can't read user B (generated sweep over the route table). `brain/tests/scenario/test_x1_isolation.py`: OpenAPI + gateway event table, private routes need a real access token, B's ids → 404 for A |
| X2 ✅ | OTP | hashed at rest; locked after 5 wrong tries. `test_x2_otp.py` (+ cooldown, expiry, single use, mail outage) |
| X3 ✅ | refresh-token reuse | session revoked. `test_x3_refresh.py` (+ 15-min access expiry, logout) |
| X4 | reconnect with `last_event_id` | missed events replayed in order, no duplicates |
| X5 | BYOK / OAuth tokens | never present in any response, log line, or socket payload (scan) |

### 4.7a R0 acceptance (`PHASES.md` R0)
| Acceptance test | Proven by |
|---|---|
| No route or socket event accepts a client `user_id` | X1 |
| Refresh reuse → session revoked; a refresh token can't open a socket | X3; `test_r0_gateway.py::test_r0_refresh_token_cannot_open_a_socket` |
| 6th wrong OTP → locked; OTP stored only as a hash | X2 |
| Two devices of one user both receive `settings.changed` | `test_r0_gateway.py::test_r0_two_devices_both_receive_settings_changed` |
| `docker compose up` → `/health` green; desktop signs in to the local brain | manual smoke (§8a) + `test_core.py::test_health_and_ready` |

### 4.8 Persona (`PERSONA.md`)
| ID | Scenario | Assertions |
|---|---|---|
| PS1 ✅ | banned phrase in a model reply ("Task completed successfully") | post-hook lint rewrites it before speaking. `test_ps1_banned_phrases_are_rewritten_before_speaking` |
| PS2 ✅ | tier-0 acknowledgements over 10 signals | no identical phrase twice in a row. `test_reflex_arc.py` |
| PS3 | job wrap-up | ≤ 3 spoken sentences: done → needs you → optional next step; details in an artifact |
| PS4 | tone tags | `[serious]` on approvals/failures involving money or other people; stripped on non-expressive engines. Brain half ✅ `test_ps4_tone_tags_travel_as_tone_not_speech` (tag → `tone`, never spoken; explained failures are `serious`); stripping is FT5 in the body |

### 4.9 Language (§25)
| ID | Scenario | Assertions |
|---|---|---|
| LG1 ✅ | "switch to Hindi" at launch | tier-1, no LLM; persona-voiced "not ready yet"; settings unchanged. `test_lg1_switch_to_hindi_is_tier1_and_changes_nothing` |
| LG2 | `set_language` to a supported language | `settings.changed` on all devices; engine plans re-selected |
| LG3 | auto-detect with a low-confidence language | reply stays in the settings language |

### 4.10 Local fallback (§11)
| ID | Scenario | Assertions |
|---|---|---|
| L1 | brain unreachable | fallback notice spoken + banner; local tool loop handles "volume up" |
| L2 | reconnect | local turns uploaded to the thread |

### 4.11 Desktop UI (§24)
Component tests: every list has loading / empty / error states; approval modal shows the exact
inputs; connect card; job panel stop. E2E (Playwright for Electron against a fake brain): sign-in,
Home conversation, Capabilities search, Engines "Run benchmark", Settings permission rule edit.

## 5. Chaos Suite

✅ R1: `brain/tests/test_chaos.py` sends 100 signals through the real gateway with a 20% failure mix
(429, 5xx, stalls after output, empty output, slow first token, malformed tool calls, failing device
tools) and asserts none is silent and every watch reaches a terminal state. Engine and device-drop
chaos joins with the body.

- 100 scripted signals with a 20% random failure rate across providers, engines, and devices.
- **Assert:** 100% end in `answered`, `done`, `cancelled`, or `failed_explained`; zero silent; p95
  first-feedback (audio or earcon) within budget in simulated time.
- Runs on every PR touching `agent/`, `supervisor/`, `gateway/`, `llm/`, or `body/`.

## 6. Latency Bench (real providers, nightly + before release)
✅ R1 tooling: every signal logs a `signal trace` (device spans: endpoint, stt_final, first_audio)
and a `signal done` line (brain spans: ack, ttft, first_delta, tool calls, end); `evals/latency.py`
turns a log into p50/p95 per span and applies the gate. The 50 scripted utterances are spoken from
the desktop app until a scripted audio driver exists.
- 50 scripted utterances through a real `spark-body` + brain in the chosen region, using free providers.
- Report p50/p95 per stage: endpoint, uplink, TTFT per provider, first sentence, TTS first audio.
- **Gate:** p50 end-of-speech → first audio < 1000 ms; p95 < 1500 ms. A regression > 10% blocks release.

## 7. Evals (live, free providers)
| Suite | Size | Measures | Used for |
|---|---|---|---|
| `reflex` ✅ | 95 (`brain/evals/reflex.jsonl`: 50 answers, 33 quick tools, 12 delegations) | answer rate, quick-tool validity (name + args), delegation, TTFT p50/p95 vs the 400 ms gate, banned phrases | reflex chain order (§5.5) |
| `agent` | ~30 multi-step tasks, stubbed tools | task success, tool-call validity, steps, tokens | agent chain order |
| `reflex_arc` ✅ | 338 (`body/evals/reflex_arc.jsonl`) | false-accept, slot accuracy | tier-0 thresholds; offline, so it runs in CI |
| `research` | ~20 questions | citation correctness, answer accuracy | research pipeline |
| `persona` ✅ (R1 part) | 58 moments (`brain/evals/persona.jsonl`: small talk, stress, can't-do, lists, numbers, failures, advice) | auto-checked PERSONA §2 rules: ≤ 3 sentences, ≤ 25 words each, no banned phrase, no markdown/lists/links/emoji, no tool call; naturalness and honesty need a human or LLM judge (later) | every reflex/agent chain entry: `uv run python -m evals.run --suite persona` |

Re-run monthly and whenever a free provider changes its offer.

## 8. Manual Smoke (before each release)
1. Fresh install → sign-in → fitness benchmark completes → engine plan shown.
2. "Hey Spark, volume 30" (instant, no LLM) → "what's a good coffee shop name" (spoken < 1 s).
3. "Open YouTube on my phone" with the phone on USB → plays.
4. "Summarize my unread mail" with Gmail disconnected → connect → summary arrives without re-asking.
5. Pull the network → local fallback announced → "volume down" still works → reconnect syncs.

## 8a. R0 Smoke (dev laptop)
1. `docker compose -f deploy/docker-compose.yml up -d --build` → `curl http://127.0.0.1:8080/health` and `/ready` are green.
2. `cd electron && npm run dev` → sign in with an email code (or Google) → the status pill reads "Connected".
3. Stop the brain container → the pill shows the reconnecting state; start it → it reconnects on its own.

## 8b. R1 Smoke (dev laptop)
1. `cd body && uv sync` (add `--extra tts` for edge-tts, `--extra hands` for exact volume via pycaw).
2. Brain up (§8a) with `GROQ_API_KEYS` in `deploy/.env`; accept the Orpheus terms in the Groq console.
3. `cd electron && npm run dev` → sign in → sidebar **Engines**: the voice engine reads "running";
   **Run benchmark** fills the table (edge-tts / groq-orpheus scores, which one is #1).
4. **Try it**: "what time is it" → answered on the device (tier 0, spoken, no brain call); "tell me
   a joke" → tier 2, reply streams in and is spoken sentence by sentence; "open notepad" → opens
   (tier 0) with a short ack; the stop button cuts speech at once.
5. Stop the brain → "tell me a joke" → spoken "I can't reach my brain right now".

## 9. v1 Baseline (for reference)
2026-10-09: `server/` unittest suite, 10 tests, 1 error (circular import in `app.socket`). v1 tests
are not carried into v2. The v1 bugs become v2 regression tests (D1, S5, T9).
