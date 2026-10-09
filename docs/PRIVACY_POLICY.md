# PRIVACY_POLICY.md — Privacy Policy (DRAFT, v2)

> **Status:** engineering draft describing the v2 design. Get legal review before publishing.
> Items marked **[planned]** ship in the phase noted in `PHASES.md`.

**Product:** Spark AI Assistant · **Controller:** Siddhant (SiddTheCoder) · **Contact:** _TBD_

---

## 1. How Spark works

Spark has a **cloud brain** (our server) and **apps on your devices** (desktop now, mobile later).
The apps listen for the wake word, turn speech into text, speak replies, and run actions on your
device. The brain handles your account, reasoning, memory, and connected services.

## 2. What we process

| Data | Where it goes | Why |
|---|---|---|
| Email, name, nickname, settings | brain (Postgres) | your account |
| **Voice audio** | stays on your device. Wake word and speech-to-text run locally. Only if your device is too slow for local speech recognition does audio go (through our brain) to Groq for transcription, and the Engines page shows this | understanding you |
| Transcribed text, Spark's replies, conversation history | brain | conversation context, history on all your devices |
| Memories (preferences, people, routines) | brain, as text + numeric embeddings | personalization; view, edit, or delete them in Settings → Memory |
| Device info (platform, hardware, battery, active app, engine benchmarks) | brain | choosing the right device and fast engines |
| Actions on your devices (files, apps, shell, phone via USB debugging) | run on your device; results go to the brain | doing what you asked |
| Connected accounts (Google, Slack, Notion, MCP servers) | encrypted tokens in the brain; data fetched only when a request needs it | doing what you asked |
| Usage and diagnostics (counts, timings, errors, incidents) | brain | quotas, reliability, debugging |

## 3. Who else receives data

| Recipient | What | When |
|---|---|---|
| **AI model providers** (Groq, NVIDIA, Cloudflare, Mistral, OpenRouter; Google Gemini only if you opt in; Anthropic only when paid providers are enabled) | your request text, recent conversation, relevant memories, tool results needed to answer | every reasoning step, routed to whichever provider is available |
| **Voice providers** | reply text (Groq Orpheus; Microsoft Edge read-aloud via edge-tts, sent from your device); audio for cloud transcription only as described above | speaking and, rarely, transcription |
| **Search** | search queries (our own SearXNG instance, which queries public search engines; DuckDuckGo) | research |
| **Maps** (OpenStreetMap) | place queries, approximate location if you ask for nearby results | places |
| **Connected services** | the actions you request | when you ask |
| **Resend** | your email address | sign-in codes |
| **Hosting** (our VPS provider) | stores the brain's database | always |

**Free-tier terms:** some free AI providers may use prompts to improve their products (for
example Google Gemini's free tier, and Mistral unless opted out, which we do). Spark only uses
providers that may train on prompts **if you turn that on** in Settings → Privacy. We never sell
your data or use it for advertising.

## 4. Security

HTTPS everywhere; identity checked on every request; per-device sessions you can revoke;
connected-account tokens and your own API keys encrypted at rest and never shown in full;
risky actions (deleting, sending, purchasing, posting) need your approval; keys and message
content are never written to logs.

## 5. Retention

Conversations, memories, and artifacts: until you delete them or your account. Usage records: 13
months. Incidents: 90 days. Audit log: 1 year. Sync events: 7 days. Sign-in codes: 24 hours.
On-device data (benchmarks, models, caches) stays on your device until you uninstall or clear it.

## 6. Your controls

- Mute the mic, use push-to-talk only, or turn off the wake word.
- See which engines your device uses (Settings → Engines) and whether any audio goes to the cloud.
- Allow or block providers that may train on prompts (Settings → Privacy).
- View, edit, and delete memories; disconnect any account (we revoke the token).
- Remove your API keys; sign out individual devices.
- **Export my data** (JSON) and **Delete my account** (removes brain data, revokes tokens; you
  clear device data by uninstalling) **[planned: R6/R7]**.

## 7. Children

Spark is not directed at children under 13.

## 8. Changes

Material changes are announced in the app and in `CHANGELOG.md`.

_Last updated: 2026-10-09 (draft for v2)_
