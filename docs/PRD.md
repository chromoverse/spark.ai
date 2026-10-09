# PRD.md — Product Requirements (v2)

**Product:** Spark, a voice-first AI assistant with a cloud brain and device bodies
**Owner:** Siddhant (SiddTheCoder)
**Stage:** v2 build (free providers only); production after R7 (`PHASES.md`)

---

## 1. Problem

Chat assistants answer but can't act on your devices. OS assistants act but are shallow and rigid.
People want one assistant they can talk to from anywhere, on any of their devices, that understands
intent, does the work across apps, accounts, and devices, and talks back like a person, fast.

## 2. Vision

Say "Hey Spark" near any of your devices. You hear an answer in under a second, simple commands
happen instantly, and bigger jobs run in the background with live progress and a human wrap-up at
the end. One brain, many bodies: laptop now, phone next, and they act as one.

## 3. Users

| Persona | Needs |
|---|---|
| Power user / developer | hands-free control of PC, phone (ADB), browser, shell; skills, plugins, MCP |
| Knowledge worker | inbox, calendar, docs, research handled and summarized by voice |
| Everyday user | instant media/system control, reminders, quick answers that just work |

## 4. Goals (measurable)

1. **Speed:** end of speech → first audio p50 < 1 s, p95 < 1.5 s. Simple commands ≈ 150–300 ms.
2. **Never silent:** 100% of signals end answered, done, cancelled, or explained (chaos suite).
3. **Safe actions:** every destructive, sending, or purchasing action is approved by the user.
4. **Cross-device:** a command spoken to one device can act on another of the user's devices.
5. **Free-first:** the build runs entirely on free providers and on-device compute.
6. **Human voice:** passes the persona eval (`PERSONA.md`).
7. **Easy install:** one installer, no Python or Node needed.

## 5. Non-goals (v1.0)

Mobile app (protocol ready, app after desktop v1.0), vision and computer use beyond screenshots,
hardware sensors, payments, languages beyond English, fully autonomous purchases.

## 6. Product pieces

| Piece | Role |
|---|---|
| Brain (cloud) | auth, reasoning, orchestration, memory, permissions, supervisor, integrations, sync |
| Desktop body | UI + sidecar with ear, mouth, hands, fitness benchmarks, watchdog, local fallback |
| Mobile body | later; same protocol |

## 7. Features

### 7.1 Talking with Spark
- Wake word or push-to-talk; typed input too
- Instant replies for simple commands (reflex arc, no LLM); conversational answers in < 1 s
- Barge-in: talk over Spark to interrupt; "stop", "never mind", "actually use my work email"
- Human, chill persona with expressive voices; verbosity and nickname settings
- English at launch; language switching and auto-detect designed in

### 7.2 Getting things done
- Agent with native tool calling: parallel steps, live job panel, plan approval for risky jobs,
  clarifying questions, human wrap-up
- ~100 tools across system, apps, files, shell, input/screen, browser, phone (ADB), Gmail,
  Calendar, Drive, Slack, Notion, web research, places, scheduling
- Skills (import from Claude Code / Codex), plugins with marketplaces, MCP servers, automations
- Workflow mode for big data jobs without token blowup
- Research with citations; documents, images, audio, and video understood; typed artifacts
  (tables, charts, maps…) with export

### 7.3 Across devices
- Same account on every device; wake-word arbitration; "on my phone / on my laptop"; capability
  fallback; queued actions for offline devices; handoffs (send to phone, continue on laptop)

### 7.4 Always reliable
- Per-device engine benchmarking; a supervisor with hedging, switching, and explicit failures;
  local model fallback when the cloud is unreachable (with a clear notice)

### 7.5 Memory
- Learns preferences, people, and routines; visible and editable Memory page; forget on request

### 7.6 App (body UI)
- Home, Activity, Capabilities, Engines, Settings; command palette; voice overlay;
  just-in-time account connect cards

## 8. Accounts & access

Email OTP + Sign in with Google; per-device sessions; one-click Google connect for
Gmail/Calendar/Drive; permissions with modes (default: auto for safe, ask for risky) and rules.

## 9. Privacy principles

1. Audio stays on the device unless the device's engine plan needs cloud STT, and that is shown.
2. Keys and tokens are encrypted and never shown in full, logged, or sent to the model.
3. Providers that train on prompts are opt-in.
4. Users can see, export, and delete their data.

## 10. Success criteria for v1.0

All `PHASES.md` exit criteria met; every `TESTING.md` matrix row green; latency bench within
budget; clean install on a fresh Windows VM; persona eval passed.

## 11. Terms

| Term | Meaning |
|---|---|
| Signal | anything the user says or types (or a schedule fires) |
| Reflex arc | tier 0: on-device handling of simple commands with no LLM |
| Reflex | tier 2: fast LLM reply that speaks first and can call quick tools |
| Agent | tier 3: multi-step tool-calling loop |
| Body / device | an app instance (desktop, later mobile) with ear, mouth, hands |
| Engine plan | the per-device ranked STT/TTS/local-LLM engines chosen by benchmark |
| Supervisor | the per-user watcher that guarantees no silent failure |
| Artifact | a typed result (table, chart, file…) shown and saved in the thread |
