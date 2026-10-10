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
cd electron && npm test                           # ✅ R2: vitest (reducers, pure UI logic)
cd electron && npm run e2e                         # Playwright vs fake brain (not built yet)
# evals (live free providers, never in PR CI)
cd brain && uv run python -m evals.run --suite reflex   # ✅ R1: 95 utterances, every keyed reflex entry
cd brain && uv run python -m evals.agent --entry groq/openai/gpt-oss-120b  # ✅ R2: 30 agent tasks, stubbed tools
cd brain && uv run python -m evals.latency < brain.log  # ✅ R1: p50/p95 first audio from signal traces
cd brain && uv run python -m evals.latency --low-spec < brain.log  # low-spec gate: p95 < 2000 ms
cd body && uv run python -m evals.clips                  # ✅ R1: the scripted ear's 50 clips (Piper)
# then start the app with SPARK_VOICE_SCRIPT=%LOCALAPPDATA%/SparkAI/latency-clips/manifest.json
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
| B2 ✅ | first provider slow (TTFT 600 ms) | hedge fires at 350 ms; second provider's stream used; first cancelled. `brain/tests/test_llm_chains.py::test_b2_hedge_at_350ms_second_stream_wins`. The hedge waits for late *for that entry* (1.3 x its usual TTFT, 350 ms at least): from Nepal a fixed 350 ms doubled every call (`test_b2_hedge_waits_for_late_by_this_entrys_usual`) |
| C1 ✅ | "open Spotify and play something calm" | speech delta and `tool.call` emitted in the same turn (parallel); done chime on success. `test_c1_*`: chime ≤ 1.5 s, spoken "Done." when slower, explained failure with a next step |
| D1 ✅ | invoice email → save PDF | agent loop: gmail_search → get_attachment → file_write on the origin device; job steps persisted; summary contains only items from tool outputs. `brain/tests/scenario/test_r2_agent.py::test_d1_invoice_email_saved_to_downloads` with stub Gmail tools (brain tools with a handler; real Gmail lands in R4) |
| D2 | D1 with Gmail not connected | connect card emitted; job paused; after fake OAuth completes, job resumes without a new signal |
| E1 ✅ | spoken to laptop: "open YouTube on my phone" | target resolved to `adb:<serial>`; tool runs on the phone sub-device; the laptop speaks the ack before the tool result. `brain/tests/scenario/test_r2_devices.py::test_e1_open_youtube_on_my_phone` with the phone as a mobile body (FakeDevice); `adb:<serial>` routing through the laptop lands with real ADB in R4 |
| E2 ✅ | E1 with the phone offline | spoken explanation + offer to queue; queued run fires when the phone comes online; expires after 1 h. `brain/tests/scenario/test_r2_devices.py::test_e2_offline_phone_gets_the_queued_run_when_it_is_back` (notice "Done on Pixel." on the laptop), `…test_e2_queued_run_expires_after_an_hour` |
| E3 ✅ | two phones, "on my phone" | asks once; the answer is saved as default; the next request doesn't ask. `brain/tests/scenario/test_r2_devices.py::test_e3_two_phones_ask_once_then_remember` (`is_default_for: ["phone"]`) |
| E4 ✅ | capability fallback: "send an SMS" from the laptop | routed to the phone with an announcement. `brain/tests/scenario/test_r2_devices.py::test_e4_capability_fallback_sends_the_sms_from_the_phone` ("Sending it from your phone.", then the approval: sending is external) |
| F1 ✅ | spoken to the phone: "pause music on my laptop" | brain routes with no LLM; the laptop gets `tool.call`. `brain/tests/scenario/test_r2_devices.py::test_f1_pause_music_on_my_laptop_from_the_phone`; no laptop on the account → the reflex (`…test_f1_not_sure_goes_to_the_reflex`) |
| G1 ✅ | handoff "send this to my phone" | artifact uploaded; phone notified; download URL valid and signed. `brain/tests/scenario/test_r2_devices.py::test_g1_send_this_to_my_phone_with_a_signed_link` (no token needed; a tampered or expired signature → 404; another user → 404) |
| G2 ✅ | "continue on my phone" | both devices see the same thread state after sync. `brain/tests/scenario/test_r2_devices.py::test_g2_continue_on_my_phone_shares_the_thread` (notice with `thread_id`, `/v2/threads/{id}/messages`, the phone's follow-up carries the laptop's turns) |

### 4.2 Wake-word arbitration (§26.2)
| ID | Scenario | Assertions |
|---|---|---|
| W1 ✅ | two devices claim within 150 ms | exactly one `wake.grant`; others `wake.yield`; the winner has the higher score + loudness. `brain/tests/scenario/test_r2_devices.py::test_w1_two_claims_one_grant` (the yielded device's next line is dropped), `…test_w1_alone_is_granted_at_once` |
| W2 ✅ | tie | the foreground / most recently used device wins. `brain/tests/scenario/test_r2_devices.py::test_w2_ties_go_to_the_foreground_then_the_most_recent` |
| W3 ✅ | a claim after the window | treated as a new signal only if its text differs; otherwise deduplicated. `brain/tests/scenario/test_r2_devices.py::test_w3_a_late_claim_is_new_only_if_the_words_differ` |

Wake word on one device (`body/tests/test_local_voice.py`):
| ID | Scenario | Assertions |
|---|---|---|
| WK1 ✅ | speech without "Hey Spark" | dropped on the device: `{ text: "", wake: false }`, no STT engine called; a follow-up (no wake asked) is transcribed |
| WK2 ✅ | "Hey Spark, what time is it" in one breath | on-device STT hears only the audio after the phrase; text "what time is it?"; a bare "Hey Spark" → `{ text: "", wake: true }` (the renderer listens 8 s). Cloud STT hears the whole utterance and the phrase is stripped from the text, joined forms ("Hayspark") too: the cut can take the command's first word (`test_wk2_cloud_stt_hears_the_whole_utterance`) |
| WK3 ✅ | spotter model not downloaded yet | open mic: transcribed with `wake: null` |

### 4.3 Reflex arc (§27)
| ID | Scenario | Assertions |
|---|---|---|
| RA1 ✅ | eval set of ~300 utterances (positives, near-misses, negatives) | false-accept rate < 0.5%; per-intent slot accuracy ≥ 98%. `body/evals/reflex_arc.jsonl` (338 rows) via `body/tests/test_reflex_arc.py`: 0 false accepts, 100% slots. Grammar only for now; the embedding classifier joins when the ONNX model ships |
| RA2 ✅ | destructive / send / purchase phrasing | never accepted by tier 0 (30 `never` rows) |
| RA3 ✅ | tier 1: "how's it going" during a job | answered from job state; no LLM call. `brain/tests/scenario/test_r2_agent.py::test_ra3_how_is_it_going_answers_from_job_state` ("0 of 2 done. Working on: file search."); without a job it's conversation (tier 2) |
| RA4 ✅ | tier 1: "yes do it" with a pending approval | resolves the approval; no LLM call. `brain/tests/scenario/test_r2_agent.py::test_ra4_yes_do_it_resolves_the_pending_approval` + `brain/tests/test_permissions.py::test_ra4_confirmations_by_voice` ("okay go ahead", "no thanks", "always allow it") |

### 4.4 Device fitness & engines (§18)
| ID | Scenario | Assertions |
|---|---|---|
| FT1 ✅ | full benchmark with fake engines (one fast, one slow) | engines that fit lead, expressive first, then fastest; the slow one only follows as a last-resort fallback; an engine that isn't installed stays out. `body/tests/test_mouth_fitness.py` |
| FT2 ✅ | quick check on start | completes ≤ 2 s; plan unchanged when scores are stable |
| FT3 ✅ | power change (battery saver) | affected roles re-probed; plan updated; the plan survives a restart |
| FT4 ✅ | selected TTS returns empty audio twice | switches to the next engine for the same sentence; incident logged |
| FT5 ✅ | tone tags | kept for Orpheus, stripped for engines without vocal-direction support |
| FT6 ✅ | edge-tts 503 | circuit opens for 10 min; fallback engine used; Engines page reason text set |
| FT7 ✅ | low-spec device (tier 0) | TTS budget 700 ms (first audio ≤ 2 s): the expressive cloud voice (650 ms) leads, fast local Piper follows; on tier ≥ 1 (250 ms) Piper leads. Quick check folds good probes into the average and spends nothing on over-budget fallbacks |
| FT8 ✅ | STT candidates | probe clip transcribed per engine: accuracy (1 − WER) then speed among those within 300 ms; slower working engines kept as fallbacks |
| FT9 ✅ | on-device models | the hardware tier picks the catalog (`body/spark_body/models.py`); download → sha256 check → safe unpack (no `../`) → `.ok`; idempotent; a bad checksum or path is rejected; a failed download → incident, retried next start; progress in `engine.plan` |
| FT10 ✅ | real models on the dev machine (skipped in CI) | Piper speaks a WAV and benchmarks; "Hey Spark, turn the volume up to thirty" → cut at the phrase → Moonshine ≥ 80% words right; near-miss "the park was sparkling" not spotted. Flaky: Piper varies per run and the cut sometimes takes "turn the volume up" (~1 run in 6) |
| FT12 ✅ | one slow call of three in a benchmark | a cloud engine gets an untimed warm-up call first; an engine whose median fits but p95 doesn't gets a probe on every start, and a good one brings it back (`test_ft12_one_slow_benchmark_call_doesnt_demote_for_good`). Owner's laptop: one 1.2 s Whisper call left Moonshine leading, and transcripts went bad. Benchmarks never overlap (one lock) |
| FT11 ✅ | CPU throttled between starts | the start-up quick check re-benchmarks a local engine that now misses its budget; it drops behind the one that fits and the plan changes before the first reply (`test_ft11_throttled_cpu_demotes_the_local_engine_on_the_next_start`). Real hardware, 16 busy loops on 8 cores (2026-10-10): Piper p95 188 → 1250 ms, Moonshine 125 → 391 ms, both out of budget |

### 4.5 Supervisor — never silent (§19)
| ID | Scenario | Assertions |
|---|---|---|
| S1 ✅ | stalled LLM stream (gap > 1.5 s) | switch to the next provider; the user hears a bridge cue. `test_s1_stalled_stream_bridges_then_next_provider_answers` + `test_llm_chains.py::test_s1_*` |
| S2 ✅ | tool times out | agent gets a tool error and re-plans; job doesn't hang. `brain/tests/scenario/test_r2_agent.py::test_s2_tool_timeout_replans_and_the_job_finishes` (`tool.cancel` at 5 s) |
| S3 ✅ | target device sleeps mid-job | re-route to another capable device, or explain. `brain/tests/scenario/test_r2_devices.py::test_s3_device_drops_mid_job_and_another_takes_over` ("That device went offline, so I'm using Desktop PC."), `…test_s3_no_other_device_means_an_explanation` |
| S4 ✅ | identical tool call 3× | loop broken; agent told; job ends explained. `brain/tests/scenario/test_r2_agent.py::test_s4_same_call_three_times_ends_explained` (the third never runs; a tool-less wrap-up, spoken `serious`) |
| S5 ✅ | grounding: summary names an event absent from tool output | blocked before speaking; regenerated or corrected (v1 calendar bug). `brain/tests/scenario/test_r2_agent.py::test_s5_grounding_blocks_an_invented_event` + `brain/tests/test_permissions.py::test_s5_grounding_finds_invented_names_times_and_files`. Claims are found by shape (quoted text, file names, times, ids, capitalized names mid-sentence); one rewrite, then a safe line |
| S6 ✅ | Groq quota exhausted | next chain entry used; health marks Groq cooling down until reset. `test_llm_chains.py::test_s6_rate_limit_falls_through_and_cools_down`; all entries down → `test_every_provider_down_is_explained_never_silent` |
| S7 ✅ | estimate miss (job 2× over estimate) | user gets a progress note with a new estimate. `brain/tests/scenario/test_r2_agent.py::test_s7_job_twice_over_its_estimate_gets_a_new_one` (supervisor sweep; spoken once, `job.update` note + `eta_s`) |
| S8 ✅ | invariant sweep | any signal past its deadline without a terminal state triggers the playbook. `test_s8_signal_past_its_deadline_is_explained` |
| S9 ✅ | the model replies with nothing | an empty stream is malformed (next entry); a whitespace-only reply gets a spoken "lost track of that one" line, never silence. `brain/tests/scenario/test_r1_voice.py::test_an_empty_reply_is_never_silence` (gpt-oss did this in the 2026-10-10 evals) |

### 4.6 Agent, tools, permissions (§5.2, §7, §20)
| ID | Scenario | Assertions |
|---|---|---|
| T1 ✅ | parallel read tools | all tool_results returned in **one** user message; ran concurrently. `brain/tests/scenario/test_r2_agent.py::test_t1_three_reads_run_in_parallel_in_one_turn` (all three `tool.call`s out before any answer) |
| T2 ✅ | malformed tool call twice | escalates to the next chain entry; history preserved. `brain/tests/scenario/test_r2_agent.py::test_t2_malformed_twice_escalates_with_the_same_history` (Groq's 400 `tool_use_failed` and schema-invalid inputs count too; so do turns with no tool call and only whitespace, `…test_t2_an_empty_turn_is_retried_not_spoken`) |
| T3 ✅ | deny → ask → allow precedence | a broad deny beats a narrow allow; a bare-tool deny removes the tool from the model's tool list. `brain/tests/scenario/test_r2_agent.py::test_t3_deny_rules_win_and_bare_denies_hide_tools` (agent and reflex) + 4 unit tests in `brain/tests/test_permissions.py` (device scope, modes, read-only shell allowlist) |
| T4 ✅ | auto-reviewer | medium-risk call matching the request is allowed; a mismatch escalates to ask. Allowed: `brain/tests/scenario/test_r2_agent.py::test_notes_txt_completes_with_progress_shown`; escalated: `brain/tests/scenario/test_r2_agent.py::test_t4_reviewer_escalates_a_call_that_doesnt_match_the_request`. Errors or timeouts escalate too |
| T5 ✅ | MCP untrusted server with `readOnlyHint` | still treated as "ask". `brain/tests/test_permissions.py::test_t5_untrusted_mcp_annotations_are_ignored` (the rule; the MCP client itself comes later) |
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

### 4.7b R1 acceptance (`PHASES.md` R1)
| Acceptance test | Proven by |
|---|---|
| Rows A1–A3, B1–B2, C1, FT1–FT10, WK1–WK3, S1/S6/S8, RA1–RA2, PS1/PS2/PS4 | the rows above, all ✅ |
| p50 < 1000 / p95 < 1500 ms over 50 scripted utterances (low-spec: p95 < 2000) | latency bench (§6), scripted ear, owner's low-spec laptop 2026-10-10: p50 1291 ms, p95 1621 ms → low-spec PASS. Tier 0 ("what time is it") p50 864 ms. The 1 s p50 needs a nearer provider region (R7) and faster STT |
| "Turn the volume up" → ack and the volume changes, no paid model | A1 (tier 0: no LLM, the chime is the ack). The bench caught Whisper's "Hayspark turned the volume up" escaping tier 0 and the reflex saying "volume's up" without the tool: fixed (joined wake forms stripped, "turned …" read as "turn …"), RA1 rows added |
| Kill the free provider → the next entry answers, under the p95 budget | S6, B2 and the all-down case on fakes. Live (2026-10-10): gpt-oss-20b's circuits opened (in the test Redis), 20 reflex prompts through the real chain → all answered by gpt-oss-120b, first token p50 469 / p95 625 ms |
| Barge-in stops TTS within 150 ms | `test_barge_in_stops_speech_within_150ms` (mouth); bench: the voice window went quiet 4–13 ms after the stop, plus the VAD onset (one or two 32 ms frames) |
| Selected TTS returns nothing → the next engine | FT4 |
| Throttle the CPU → the plan changes on the next start | FT11 |
| Chaos: 100 signals, none silent | §5 |

### 4.7c R2 acceptance (`PHASES.md` R2, in progress)
| Acceptance test | Proven by |
|---|---|
| "Create notes.txt on the desktop, write my to-dos, open it" completes with progress shown | `brain/tests/scenario/test_r2_agent.py::test_notes_txt_completes_with_progress_shown` (todo, steps, note, wrap-up; real hands: body tests) |
| "Delete everything in Downloads" → approval required; deny → nothing deleted | `brain/tests/scenario/test_r2_agent.py::test_delete_downloads_asks_and_deny_deletes_nothing` (+ multi-device first-answer-wins, plan approval, "always") |
| "Stop" mid-job cancels within 500 ms; "use the D drive instead" steers the running job | `brain/tests/scenario/test_r2_agent.py::test_stop_mid_job_cancels_within_500ms`, `…test_stop_said_to_the_brain_cancels_the_job`, `…test_steer_use_the_d_drive_reaches_the_running_job`; barge-in leaves jobs alone |
| 3 independent reads run in parallel | T1 |
| Malformed free-model tool calls twice → next chain entry, job completes | T2 |
| Desktop hands ported from v1 (one test per tool) | `body/tests/test_hands.py`: files for real in a temp folder (write/read/edit, base64, list/search, move, delete to the Recycle Bin, guards, organize + restore with special and unicode names), shell, clipboard, screenshot, keyboard (surrogate pairs), hotkeys, mouse, processes, app list/close, system info, lock/sleep; OS errors become actionable failures; every brain device tool has a hand |

### 4.8 Persona (`PERSONA.md`)
| ID | Scenario | Assertions |
|---|---|---|
| PS1 ✅ | banned phrase in a model reply ("Task completed successfully") | post-hook lint rewrites it before speaking. `test_ps1_banned_phrases_are_rewritten_before_speaking` |
| PS2 ✅ | tier-0 acknowledgements over 10 signals | no identical phrase twice in a row. `test_reflex_arc.py` |
| PS3 ✅ | job wrap-up | ≤ 3 spoken sentences: done → needs you → optional next step; details in an artifact. `brain/tests/scenario/test_r2_agent.py::test_ps3_wrap_up_is_three_sentences_and_the_rest_is_an_artifact` |
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
| ID | Scenario | Assertions |
|---|---|---|
| U1 ✅ | voice overlay (the notch at the top of the screen) shows the right thing | rests small; opens for a bare "Hey Spark", a pending reply and Spark's voice; approvals/questions outrank everything; a running job shows as a small live pill, full on hover; a turn the brain never finishes stops "thinking" after 30 s; a finished exchange lingers 7 s. `electron/src/renderer/pages/overlay/overlayMode.test.ts` |
| U2 ✅ | brain events fold into what the UI shows | sentences join the user's turn by signal id and end it; a job speaking after its turn is a new line; approval cards close on any device's answer and when the job ends; the current job is the newest active one. `electron/src/renderer/store/features/spark/sparkSlice.test.ts` |
| U3 | overlay never jumps or clips (owner's recording, 2026-10-10) | the window is fixed and click-through, only the notch morphs; checked by hand in a browser harness (per-frame size: no reversals, 0 px centre drift). Automate with Playwright for Electron |

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
turns a log into p50/p95 per span (first audio also per tier) and applies the gate.
✅ Scripted ear: `body/evals/clips.py` speaks the 50 lines of `body/evals/latency.jsonl` as "Hey
Spark, …" in five Piper voices; started with `SPARK_VOICE_SCRIPT=<manifest>`, the desktop app feeds
each clip through the live ear's timing (candidate, commit 450 ms later) and the real loop (wake
check, STT plan, tier 0, brain, TTS, playback), stops two replies to time barge-in, and prints
p50/p95. 2026-10-10 on the owner's low-spec laptop (Nepal → Groq): p50 1291 / p95 1621 ms (endpoint
704, STT 313, wake check ~80, TTFT 449 at p50); the speculative brain start took p95 from 1732 to
1621 ms. 3 of 50 clips missed the wake word ("He sparked …" on Piper voices).
- 50 scripted utterances through a real `spark-body` + brain in the chosen region, using free providers.
- Report p50/p95 per stage: endpoint, uplink, TTFT per provider, first sentence, TTS first audio.
- **Gate:** p50 end-of-speech → first audio < 1000 ms; p95 < 1500 ms. A regression > 10% blocks release.

## 7. Evals (live, free providers)
| Suite | Size | Measures | Used for |
|---|---|---|---|
| `reflex` ✅ | 95 (`brain/evals/reflex.jsonl`: 50 answers, 33 quick tools, 12 delegations) | answer rate, quick-tool validity (name + args), delegation, TTFT p50/p95 vs the 400 ms gate, banned phrases | reflex chain order (§5.5) |
| `agent` ✅ | 30 multi-step tasks (`brain/evals/agent.jsonl`), stubbed tools | task success, tool-call validity, malformed turns, parallel calls, turns, tokens, wrap-up style + grounding | agent chain order. 2026-10-10: gpt-oss-120b 22/30, gpt-oss-20b 23/30, qwen3.8-27b 21/30 (4 rate-limited); every call valid; misses are run-to-run flaky (a rerun of 4 missed tasks passed 3) |
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
1. `cd body && uv sync --extra tts --extra hands --extra local` (edge-tts, exact volume via pycaw,
   on-device wake word / STT / TTS via sherpa-onnx). On first start the body downloads this PC's
   models (low-spec: wake spotter, Piper, Moonshine-tiny, ~210 MB) into `%LOCALAPPDATA%\SparkAI\models`.
2. Brain up (§8a) with `GROQ_API_KEYS` in `deploy/.env`; accept the Orpheus terms in the Groq console.
   R1 adds a migration (`incidents`): the brain container runs it on start; a host-run brain needs
   `cd brain && uv sync && uv run alembic upgrade head`.
3. `cd electron && npm run dev` → sign in → sidebar **Engines**: the voice engine reads "running";
   **Run benchmark** fills the table (edge-tts / groq-orpheus scores, which one is #1).
4. **Try it**: "what time is it" → answered on the device (tier 0, spoken, no brain call); "tell me
   a joke" → tier 2, reply streams in and is spoken sentence by sentence; "open notepad" → opens
   (tier 0) with a short ack; the stop button cuts speech at once.
5. Stop the brain → "tell me a joke" → spoken "I can't reach my brain right now".
6. Engines page: "Wake word ready" shows; the table lists `piper` and `moonshine-tiny` with their
   numbers. Mic on → say "what time is it" (ignored: no wake word) → "Hey Spark, what time is it"
   → answered; then up to 2 follow-ups, each within 6 s of Spark finishing, need no wake word (a
   third is ignored). When Spark ends on a question ("Want me to…?"), one answer ("yes, do it")
   needs no wake word (8 s). At most 4 lines in a row skip "Hey Spark". Talking while Spark speaks
   stops it (0.2 s of speech, or at once mid-exchange) and that line needs no wake word; "Hey
   Spark, wait" stops it too. "What's my battery" → answered on the device. "Hey Spark" alone → a chime, then
   the command.

## 9. v1 Baseline (for reference)
2026-10-09: `server/` unittest suite, 10 tests, 1 error (circular import in `app.socket`). v1 tests
are not carried into v2. The v1 bugs become v2 regression tests (D1, S5, T9).
