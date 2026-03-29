# Spark Voice Daemon

`voice_daemon/` is the always-on microphone worker for Spark. It owns the mic,
waits for the Spark wake phrases, streams captured audio to the server, and can
play TTS while the desktop is locked.

## Quick Start

```powershell
python -m venv spark_voice_daemon
.\spark_voice_daemon\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env.local
python scripts\install_models.py
python main.py
```

## Configuration Sources

The daemon now reads configuration from two places:

1. `.env` or `.env.local`
   Use this for secrets and service wiring such as `DAEMON_SERVICE_TOKEN`,
   `SPARK_SERVER_URL`, audio settings, and log level.
2. Shared Spark desktop config
   The wake-word section is persisted in the shared `config.json` used by the
   desktop runtime.

Default shared config path:

- Windows: `%USERPROFILE%\AppData\Local\SparkAI\config.json`
- macOS: `~/Library/Application Support/SparkAI/config.json`
- Linux: `~/.local/share/SparkAI/config.json`

Compatibility override:

- `JARVIS_DATA_DIR` changes the base app-data directory for this file.

The daemon seeds this section automatically if it is missing:

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

`config.json` wins for wake-word settings. `.env` values are only used as the
fallback that seeds missing keys.

## Required Model Files

Spark wake detection depends on two custom ONNX files in `voice_daemon/models`:

- `hey_spark.onnx`
- `spark.onnx`

The daemon fails fast during startup if either file is missing. `install_models.py`
downloads the base openWakeWord and Silero assets, but it does not generate or
download these custom Spark models for you.

## Required Environment Variables

See `.env.example` for the full template. The minimum required secret is:

- `DAEMON_SERVICE_TOKEN`

Optional but commonly set values:

- `SPARK_ENV_PATH`
- `SPARK_SERVER_URL`
- `MODELS_DIR`
- `LOG_LEVEL`
- `MIC_DEVICE_INDEX`

## Notes

- Runtime identity stays `client_type="daemon"` for socket auth compatibility.
- Wake-word config is loaded on startup; restart the daemon after editing
  `config.json`.
