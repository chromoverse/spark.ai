# voice_daemon — State Reference

## File Inventory

```
voice_daemon/
├── .env.example              # Template for env vars (checked in, no secrets)
├── README.md                 # Quick-start docs
├── requirements.txt          # Python dependencies
├── main.py                   # Entry point / boot orchestrator
├── config/
│   ├── __init__.py           # empty
│   └── settings.py           # Two-layer config loader (env + shared JSON)
├── core/
│   ├── __init__.py           # empty
│   ├── state.py              # Finite state machine (IDLE → WAKE → LISTENING → STREAMING → PROCESSING → IDLE)
│   ├── mic.py                # Microphone capture (16 kHz, float32, 20 ms frames)
│   ├── vad.py                # Voice activity detection (Silero VAD, 512-sample windows)
│   └── wake_word.py          # Wake-word detection (openwakeword + custom ONNX models)
├── stream/
│   ├── __init__.py           # empty
│   ├── socket_client.py      # Socket.IO client to Spark server
│   ├── chunker.py            # Float32 mic frames → PCM16 ~2 s chunks
│   └── poster.py             # Empty placeholder (future HTTP upload)
├── health/
│   ├── __init__.py           # empty
│   └── server_watch.py       # Polls server /health before boot; liveness check helper
├── playback/
│   ├── __init__.py           # empty
│   ├── tts_player.py         # TTS playback (screen-locked only)
│   └── ding.py               # Plays ding.wav on wake word
├── assets/
│   └── ding.wav              # Wake-word confirmation sound (binary)
├── models/
│   ├── .gitkeep              # placeholder
│   └── README.md             # Notes that hey_spark.onnx + spark.onnx must be placed manually
├── scripts/
│   └── install_models.py     # Downloads base openwakeword + Silero VAD models
└── tests/
    ├── test_main.py          # Smoke test: full boot sequence
    ├── test_settings.py      # Config seeding & precedence tests
    ├── test_wake_word.py     # Model path, fail-fast, prediction mapping
    ├── test_mic.py           # empty
    └── test_vad.py           # empty
```

## How It Works — Boot Sequence

`main.py` runs this sequence on every start:

1. **Load config** — imports `config.settings`, which resolves `.env` and shared `config.json`, validates values, and populates module-level globals.  Fails fast if `DAEMON_SERVICE_TOKEN` is missing.
2. **Wait for server** — `health/server_watch.py` polls `GET <SERVER_URL>/health` until it returns 200 (default timeout 60 s).
3. **Load ML models** — `wake_word.load()` and `vad.load()` run in a thread pool so they don't block the event loop.
4. **Open mic** — `mic.start(loop)` opens a permanent `sounddevice.InputStream` at 16 kHz mono float32.  The daemon owns the mic for its entire lifetime.
5. **Connect Socket.IO** — `socket_client` connects to the server over WebSocket (polling fallback), authenticating with `DAEMON_SERVICE_TOKEN` and `client_type="daemon"`.
6. **Register TTS player** — wires `tts_player` callbacks to socket events.
7. **Run forever** — `socket_client.wait()` blocks.  On SIGINT/SIGTERM the mic is closed and the process exits cleanly.

### --download-models flag

`python main.py --download-models` downloads base openwakeword + Silero VAD models to `models/`, then exits.  Custom wake-word models (`hey_spark.onnx`, `spark.onnx`) must still be placed manually.

## FSM (Finite State Machine)

Defined in `core/state.py`.  Singleton instance, thread-safe via `asyncio.Lock`.

```
IDLE ──► WAKE ──► LISTENING ──► STREAMING ──► PROCESSING ──► IDLE
  ▲                 │                │
  └─────────────────┘ (silence)      │
  ▲                                  │
  └──────────────────────────────────┘ (socket drop)
```

| State        | Meaning                                                          |
|--------------|------------------------------------------------------------------|
| IDLE         | Mic open, only wake-word detection runs                          |
| WAKE         | Wake word confirmed, ding.wav is playing                         |
| LISTENING    | Ding done, Silero VAD active, waiting for speech                 |
| STREAMING    | Speech detected, PCM chunks being sent to server                 |
| PROCESSING   | Speech ended, waiting for server response                        |

`is_busy()` returns `True` during STREAMING/PROCESSING — wake-word triggers are suppressed.

## Environment Management

Two configuration layers, merged at startup:

### Layer 1 — `.env` file (secrets + operational params)

Resolution order for the `.env` path:

1. `SPARK_ENV_PATH` env var (explicit override)
2. `C:\spark\.env` (Windows) / `/opt/spark/.env` (Linux/macOS)
3. `<repo_root>/.env` (dev fallback)
4. `<voice_daemon>/.env.local` (last resort)

Loaded via `python-dotenv`.  **Required**: `DAEMON_SERVICE_TOKEN`.  Everything else has defaults.

Key env vars:

| Variable                       | Default                     | Purpose                          |
|--------------------------------|-----------------------------|----------------------------------|
| `SPARK_SERVER_URL`             | `http://127.0.0.1:8000`     | Backend server URL               |
| `DAEMON_SERVICE_TOKEN`         | *(required)*                | Auth token for socket connection |
| `SAMPLE_RATE` / `CHUNK_MS`    | `16000` / `20`              | Audio capture params             |
| `VAD_*`                        | various                     | Silero VAD tuning                |
| `WAKE_WORD_*`                  | `hey spark,spark` / `0.5`   | Seed values for config.json      |
| `MODELS_DIR`                   | `<voice_daemon>/models/`    | Where ONNX models live           |
| `LOG_LEVEL`                    | `INFO`                      | Python logging level             |

### Layer 2 — shared `config.json` (user-tunable wake-word settings)

Path: `~/AppData/Local/SparkAI/config.json` (Windows), overridden by `JARVIS_DATA_DIR`.

Structure:

```json
{
  "voice_daemon": {
    "wake_phrases": ["hey spark", "spark"],
    "wake_models": ["hey_spark", "spark"],
    "wake_threshold": 0.5,
    "wake_cooldown_s": 1.0
  }
}
```

**Seeding rule**: if `config.json` doesn't exist or is missing the `voice_daemon` section, values from `.env` are written in.  After that, `config.json` wins — `.env` wake-word values are only used to fill absent keys.

**Validation**: threshold must be in (0, 1], cooldown >= 0, positive VAD threshold > negative VAD threshold.

## How It Talks to the Server

### Transport: Socket.IO (WebSocket, polling fallback)

File: `stream/socket_client.py`

Connection:

- URL: `SPARK_SERVER_URL` (default `http://127.0.0.1:8000`)
- Auth payload: `{"token": DAEMON_SERVICE_TOKEN, "client_type": "daemon"}`
- Auto-reconnect: unlimited attempts, 2 s initial delay, 30 s max delay

### Outbound events (daemon → server)

| Event                 | Trigger                        | Payload fields                          |
|-----------------------|--------------------------------|-----------------------------------------|
| `user-speech-started` | VAD detects speech start       | `sessionId`, `timestamp`, `source`      |
| `user-speaking`       | Every ~2 s chunk               | `audio` (PCM16 bytes), `mimeType`, `sessionId`, `seq`, `timestamp`, `source` |
| `user-stop-speaking`  | VAD detects speech end         | `sessionId`, `timestamp`, `source`      |
| `user-interrupt`      | User interrupts TTS playback   | `timestamp`, `source`                   |

### Inbound events (server → daemon)

| Event             | Handler                                      |
|-------------------|----------------------------------------------|
| `tts-start`       | `tts_player._on_tts_start` — init playback   |
| `tts-chunk`       | `tts_player._on_tts_chunk` — queue audio     |
| `tts-end`         | `tts_player._on_tts_end` — finish playback   |
| `tts-interrupt`   | `tts_player._on_tts_interrupt` — stop        |
| `ai-end`          | FSM PROCESSING → IDLE                        |
| `query-result`    | FSM PROCESSING → IDLE                        |
| `query-error`     | FSM PROCESSING → IDLE                        |
| `error`           | FSM PROCESSING → IDLE                        |

### Health check

File: `health/server_watch.py`

- `wait_for_server()` — blocking poll of `GET /health` during boot
- `is_server_alive()` — single non-blocking check (used before socket reconnect)

### Audio chunking

File: `stream/chunker.py`

- Accumulates float32 mic frames; flushes when 32 000 samples (~2 s at 16 kHz) are reached
- Converts to int16 PCM bytes before emitting via socket
- `flush(force=True)` drains remaining audio on speech end

## How It Listens

The daemon **always has the mic open**.  Listening is not a mode that starts and stops — the mic stream is opened once at boot and never released.

### Frame routing (in `core/mic.py`)

The `sounddevice` C-thread callback fires every 20 ms (320 samples).  Each frame is routed by FSM state:

| FSM state   | Frame destination                     |
|-------------|---------------------------------------|
| IDLE        | `wake_word.process_frame()`           |
| WAKE        | dropped                               |
| LISTENING   | dropped (VAD pulls from mic buffer)   |
| STREAMING   | `chunker.push_frame()`                |
| PROCESSING  | dropped                               |

### Wake-word detection (`core/wake_word.py`)

- Uses openwakeword with custom ONNX models (`hey_spark.onnx`, `spark.onnx`)
- Converts float32 → int16, runs prediction per frame
- If best score >= `wake_threshold` AND cooldown elapsed → triggers WAKE transition + ding

### Voice activity detection (`core/vad.py`)

- Silero VAD requires exactly 512-sample windows at 16 kHz (32 ms)
- Frames accumulate until a full window is available
- **Speech start**: enough consecutive positive frames (controlled by `VAD_MIN_SPEECH_MS`) → transition to STREAMING, begin chunker session, emit `user-speech-started`
- **Speech end**: enough consecutive negative frames (controlled by `VAD_REDEMPTION_MS`) → flush chunker, emit `user-stop-speaking`, transition to PROCESSING
- **Silence timeout**: 8 s in LISTENING without speech → reset to IDLE

### TTS playback (`playback/tts_player.py`)

Plays TTS audio **only when the screen is locked**.  When unlocked, the Electron desktop app handles TTS.

Screen-lock detection:
- **Windows**: `GetForegroundWindow()` + `OpenInputDesktop()` both fail at lock screen
- **macOS**: `CGSessionCopyCurrentDictionary` → `CGSSessionScreenIsLocked`
- **Linux**: `loginctl` or D-Bus GNOME screensaver

Audio is queued via `asyncio.Queue`, accumulated, and played through `sounddevice` at the samplerate from `tts-start` (default 22050 Hz), scaled by `TTS_VOLUME`.

## Known Limitations / TODOs

- `stream/poster.py` is empty — HTTP-based audio upload not yet implemented
- `test_mic.py` and `test_vad.py` are empty placeholders
- Server-side code currently only accepts user JWTs; needs a change to accept `DAEMON_SERVICE_TOKEN` (comment block in `socket_client.py` documents the exact patch)
- Watchdog timeout logic in `main.py` is stubbed with a TODO
