```
[POWER ON]
    ↓
OS boots
    ↓
System services start ──────────────────────────────────────┐
    ↓                                                        │
Server starts on :8000          ✅ running                   │
    ↓                                                        │
Voice Daemon starts             ✅ running, mic listening    │
    ↓                                                        │
[USER LOGIN SCREEN]                                          │
    ↓                                                        │  
User logs in                                                 │
    ↓                                                        │
Electron starts (autostart)                                  │
    ↓                                                        │
Electron connects to server ────────────────────────────────┘
ws://localhost:8000
    ↓
[NORMAL USE]
User speaks → daemon captures → server processes → Electron shows UI
    ↓
[SCREEN LOCKS]
    ↓
Electron → stays in RAM, hidden behind lock screen
Server  → still running ✅ (system level)
Daemon  → still listening ✅ (system level)
    ↓
User speaks → daemon captures → server processes
            → TTS plays back via speakers ✅ (audio works on lock screen)
            → Electron UI updates (hidden, but ready)
    ↓
[SCREEN UNLOCKS]
    ↓
Electron visible again, shows what happened while locked
```


# YourApp — Always-On Voice Assistant Architecture

## Overview

YourApp runs as **3 persistent processes** that together ensure the assistant is always
listening, always ready — even before you log in, even when the screen is locked.

---

## The 3 Processes

| # | Process | What It Does | Level | Autostart |
|---|---|---|---|---|
| 1 | **Server** | FastAPI backend — STT, RAG, LLM, TTS | System | Boot |
| 2 | **Voice Daemon** | Mic capture, wake word, audio streaming | System | Boot |
| 3 | **Electron App** | UI, TTS playback, visual responses | User | Login |

---

## Architecture Diagram

```
OS BOOT
  │
  ├──▶ [1] SERVER starts          (system service, port 8000)
  │         - Groq STT
  │         - RAG pipeline
  │         - LLM (streaming tokens)
  │         - TTS generation
  │
  ├──▶ [2] VOICE DAEMON starts    (system service, depends on server)
  │         - Holds microphone exclusively
  │         - Wake word detection (openwakeword)
  │         - Silero VAD (end-of-speech detection)
  │         - Streams audio chunks → server
  │         - Plays ding.wav on wake
  │         - Plays TTS audio when screen is locked
  │
USER LOGS IN
  │
  └──▶ [3] ELECTRON APP starts    (user autostart)
            - Connects to already-running server via WebSocket
            - Shows UI, transcripts, responses
            - Plays TTS audio when screen is unlocked
            - Reconnects automatically if server restarts
```

---

## Full Voice Flow

```
                    ┌─ Groq STT ◀── audio chunks
User speaks ──▶ Daemon              │
                    └─ server ◀─────┘
                         │
                    ┌────┴────┐
                    │         │
                   RAG       (fires on first word, not after silence)
                    │
                    └──▶ LLM (transcript + RAG context)
                              │
                         streaming tokens
                              │
                    ┌─────────┴──────────┐
                    │                    │
                   TTS              Electron UI
              (parallel with        (shows text,
               token generation)     transcript)
                    │
          ┌─────────┴─────────┐
          │                   │
    screen locked?       screen unlocked?
          │                   │
       Daemon               Electron
      plays audio           plays audio
```

---

## Lock Screen Behavior

```
[SCREEN LOCKS]
      │
      ├── Server        ✅  still running   (system level)
      ├── Voice Daemon  ✅  still listening  (system level)
      └── Electron      ✅  in RAM, hidden   (audio output suspended)

[USER SPEAKS WHILE LOCKED]
      │
      ├── Daemon hears wake word
      ├── ding.wav plays immediately        (speakers work on lock screen)
      ├── Audio streamed to server
      ├── Server: STT → RAG → LLM → TTS
      └── Daemon plays TTS response         (via sounddevice, system level)

[SCREEN UNLOCKS]
      │
      ├── Electron becomes visible
      ├── Shows transcript + response from while locked
      └── Resumes playing TTS directly
```

---

## Startup Order & Dependencies

```
Boot
 │
 ▼
[1] Server ──────────────────────────────── starts first
                                             health: GET /health
 │  (server healthy)
 ▼
[2] Voice Daemon ────────────────────────── starts second
                                             waits for server /health
                                             then begins mic capture
 │  (user logs in)
 ▼
[3] Electron ────────────────────────────── starts third
                                             polls /health every 500ms
                                             shows loading until server ready
                                             then opens main window
```

---

## Audio Pipeline Detail

### While You Speak (parallel)
```
Daemon mic capture
  │
  ├── chunk 1 (20ms) ──▶ server /audio/chunk ──▶ buffers audio
  ├── chunk 2 (20ms) ──▶ server /audio/chunk ──▶ fires RAG on first chunk
  ├── chunk 3 (20ms) ──▶ server /audio/chunk
  └── ...

RAG is already querying your knowledge base
while you are still speaking.
```

### When You Stop Speaking (Silero VAD detects silence)
```
Daemon ──▶ server /audio/end
                │
                ├── Groq STT (full audio buffer) ──▶ transcript ~200ms
                │
                └── RAG result (already done ✅)
                          │
                          ▼
                     LLM prompt:
                     {transcript} + {rag_context}
                          │
                     streaming tokens
                          │
               ┌──────────┴──────────┐
               │                     │
         TTS chunks              WebSocket
         generated in          ──▶ Electron
         parallel                   UI update
```

### Latency Breakdown
```
0ms      wake word detected
0ms      ding.wav plays              ← user feels heard instantly
~800ms   user finishes speaking      (VAD detects silence)
~1000ms  Groq transcript ready       (+200ms)
~1000ms  RAG already complete        (was running since 0ms)
~1200ms  LLM first token             (+200ms)
~1250ms  TTS first chunk plays       (+50ms, parallel)

Total: ~1.25s from stop speaking → hearing response
```

---

## Autostart Setup by OS

### Windows

| Process | Method | Command |
|---|---|---|
| Server | Windows Service | `sc config YourAppServer start= auto` |
| Daemon | Windows Service | `sc config YourAppDaemon start= auto` |
| Electron | Registry Run key | `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` |

### macOS

| Process | Method | Location |
|---|---|---|
| Server | LaunchDaemon | `/Library/LaunchDaemons/com.yourapp.server.plist` |
| Daemon | LaunchDaemon | `/Library/LaunchDaemons/com.yourapp.daemon.plist` |
| Electron | LaunchAgent | `~/Library/LaunchAgents/com.yourapp.electron.plist` |

> **LaunchDaemon** = system level, no user needed  
> **LaunchAgent** = user level, starts on login

### Linux

| Process | Method | Location |
|---|---|---|
| Server | systemd service | `/etc/systemd/system/yourapp-server.service` |
| Daemon | systemd service | `/etc/systemd/system/yourapp-daemon.service` |
| Electron | XDG autostart | `~/.config/autostart/yourapp.desktop` |

---

## Install Everything — One Command

```bash
# Installs all 3 processes + registers autostart for current OS
# Requires admin/sudo

python scripts/service_manager.py install

# Remove everything
python scripts/service_manager.py uninstall

# Check status of all 3
python scripts/service_manager.py status
```

---

## Process Communication

```
Voice Daemon  ──── HTTP POST ────▶  Server
                /audio/chunk          (streams while speaking)
                /audio/end            (signals stop)

Server        ──── WebSocket ───▶  Electron
                ws://localhost:8000   (pushes TTS chunks + transcript)

Electron      ──── HTTP GET ────▶  Server
                /health               (polls on startup until ready)

Server        ──── HTTP ────────▶  Groq API
                                      (STT transcription)

Server        ──── HTTP ────────▶  LLM API
                                      (streaming response)
```

---

## Project Structure

```
yourapp/
│
├── server/
│   ├── main.py                   ← FastAPI app entry point
│   ├── stt.py                    ← Groq STT integration
│   ├── rag.py                    ← RAG pipeline
│   ├── llm.py                    ← LLM streaming
│   └── tts.py                    ← TTS generation
│
├── daemon/
│   ├── main.py                   ← entry point, listen loop
│   ├── wake_word.py              ← openwakeword detection
│   ├── vad.py                    ← Silero VAD (end-of-speech)
│   ├── audio_stream.py           ← mic capture + chunked POST
│   └── playback.py               ← ding.wav + TTS audio playback
│
├── electron/
│   ├── main.js                   ← Electron entry, health polling
│   ├── preload.js
│   └── renderer/                 ← UI
│
├── scripts/
│   ├── service_manager.py        ← install/uninstall/status all OS
│   ├── install_service.py        ← Windows Service helper (pywin32)
│   ├── com.yourapp.server.plist  ← macOS server LaunchDaemon
│   ├── com.yourapp.daemon.plist  ← macOS daemon LaunchDaemon
│   └── yourapp-*.service         ← Linux systemd units
│
├── assets/
│   └── ding.wav                  ← wake word feedback sound
│
├── .env                          ← GROQ_API_KEY, etc. (absolute path)
└── README.md                     ← this file
```

---

## Environment Variables

Since Server and Daemon run as root/SYSTEM they cannot read your user `.env`.
Always use an **absolute path** when loading env:

```python
# server/main.py and daemon/main.py — top of file
from dotenv import load_dotenv
load_dotenv("/opt/yourapp/.env")      # Linux / macOS
# load_dotenv("C:/yourapp/.env")      # Windows
```

`.env` file:
```
GROQ_API_KEY=your_key_here
LLM_API_KEY=your_key_here
SERVER_PORT=8000
WAKE_WORD=hey_jarvis
```

---

## Crash Recovery

All 3 processes restart automatically on crash:

| Process | Restart delay | Max retries |
|---|---|---|
| Server | 5s | unlimited |
| Daemon | 3s (after server healthy) | unlimited |
| Electron | on next login | — |

If server crashes and restarts, daemon automatically reconnects.  
If daemon crashes and restarts, it re-acquires the mic and resumes.  
If Electron crashes, it reopens — server and daemon unaffected.

---

## Key Design Principles

- **Daemon owns the mic** — Electron never touches audio input directly
- **Server is the brain** — all AI logic lives here, nothing else decides anything  
- **Electron is just a screen** — renders what server tells it, replaceable
- **Daemon is dumb** — wake word, ding, record, POST. Nothing else
- **RAG fires early** — starts on first audio chunk, not after silence
- **TTS is parallel** — first chunk plays before LLM finishes generating
- **Graceful degradation** — if Electron is closed, voice still works end-to-end