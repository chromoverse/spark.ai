"""
config/settings.py

Single source of truth for all voice_daemon configuration.
Secrets and operational settings come from the daemon .env file.
User-tunable wake word settings live in the shared Spark desktop config.json.
"""

from __future__ import annotations

import json
import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

APP_NAME = "SparkAI"
VOICE_DAEMON_SECTION = "voice_daemon"
DEFAULT_WAKE_PHRASES = ("hey spark", "spark")
DEFAULT_WAKE_MODELS = ("hey_spark", "spark")


def _resolve_env_path() -> Path:
    explicit = os.environ.get("SPARK_ENV_PATH")
    if explicit and os.path.isfile(explicit):
        return Path(explicit)

    if sys.platform == "win32":
        default = Path(r"C:\spark\.env")
    else:
        default = Path("/opt/spark/.env")

    if default.is_file():
        return default

    here = Path(__file__).resolve().parent
    dev_path = (here / ".." / ".." / ".env").resolve()
    if dev_path.is_file():
        return dev_path

    return (here / ".." / ".env.local").resolve()


_ENV_PATH = _resolve_env_path()
load_dotenv(_ENV_PATH, override=False)


def _require(key: str) -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        raise RuntimeError(
            f"[voice_daemon] Required env var '{key}' is missing or empty.\n"
            f"  env file checked: {_ENV_PATH}\n"
            f"  Set it there or export it before starting the daemon."
        )
    return val


def _optional(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _parse_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _optional_list(*keys: str, default: tuple[str, ...]) -> tuple[str, ...]:
    for key in keys:
        raw = _optional(key)
        if raw:
            items = _parse_csv(raw)
            if items:
                return items
    return default


def _default_user_data_dir() -> Path:
    try:
        home = Path.home()
    except RuntimeError as exc:
        fallback_home = os.environ.get("USERPROFILE") or os.environ.get("HOME")
        if not fallback_home:
            raise RuntimeError(
                "[voice_daemon] Could not determine the current user's home directory.\n"
                "  Set JARVIS_DATA_DIR explicitly for the daemon."
            ) from exc
        home = Path(fallback_home)

    system = platform.system()
    if system == "Windows":
        return home / "AppData" / "Local" / APP_NAME
    if system == "Darwin":
        return home / "Library" / "Application Support" / APP_NAME
    return home / ".local" / "share" / APP_NAME


def _resolve_shared_config_path() -> Path:
    configured_user_data_dir = _optional("JARVIS_DATA_DIR")
    if configured_user_data_dir:
        user_data_dir = Path(configured_user_data_dir).expanduser()
    else:
        user_data_dir = _default_user_data_dir()
    user_data_dir.mkdir(parents=True, exist_ok=True)
    return user_data_dir / "config.json"


def _read_shared_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"[voice_daemon] Shared config is invalid JSON: {path}\n"
            f"  {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise RuntimeError(
            f"[voice_daemon] Shared config must contain a JSON object at the root: {path}"
        )
    return data


def _write_shared_config(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def _coerce_config_list(value: Any, *, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        items = _parse_csv(value)
    elif isinstance(value, list):
        items = tuple(str(item).strip() for item in value if str(item).strip())
    else:
        raise RuntimeError(
            f"[voice_daemon] Shared config field '{field_name}' must be a list of strings."
        )

    if not items:
        raise RuntimeError(
            f"[voice_daemon] Shared config field '{field_name}' cannot be empty."
        )
    return items


def _coerce_float(value: Any, *, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"[voice_daemon] Shared config field '{field_name}' must be numeric."
        ) from exc


def _resolve_wake_model_path(entry: str, models_dir: Path) -> Path:
    candidate = Path(entry)
    if candidate.is_absolute():
        return candidate
    if candidate.suffix.lower() == ".onnx":
        return (models_dir / candidate).resolve()
    return (models_dir / f"{entry}.onnx").resolve()


def _seed_or_load_voice_daemon_config(shared_config_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    root = _read_shared_config(shared_config_path)

    existing_section = root.get(VOICE_DAEMON_SECTION)
    if existing_section is None:
        section: dict[str, Any] = {}
    elif isinstance(existing_section, dict):
        section = dict(existing_section)
    else:
        raise RuntimeError(
            f"[voice_daemon] Shared config field '{VOICE_DAEMON_SECTION}' must be a JSON object."
        )

    fallback_section = {
        "wake_phrases": list(
            _optional_list("WAKE_WORD_PHRASES", default=DEFAULT_WAKE_PHRASES)
        ),
        "wake_models": list(
            _optional_list(
                "WAKE_WORD_MODELS",
                "WAKE_WORD_MODEL",
                default=DEFAULT_WAKE_MODELS,
            )
        ),
        "wake_threshold": float(_optional("WAKE_WORD_THRESHOLD", "0.5")),
        "wake_cooldown_s": float(_optional("WAKE_WORD_COOLDOWN_S", "1.0")),
    }

    updated = False
    for key, value in fallback_section.items():
        if key not in section:
            section[key] = value
            updated = True

    if root.get(VOICE_DAEMON_SECTION) != section:
        root[VOICE_DAEMON_SECTION] = section
        updated = True

    if updated or not shared_config_path.exists():
        _write_shared_config(shared_config_path, root)

    return root, section


@dataclass(frozen=True)
class RuntimeSettings:
    env_path: Path
    shared_config_path: Path
    shared_config: dict[str, Any]
    voice_daemon_config: dict[str, Any]
    server_url: str
    daemon_service_token: str
    wake_phrases: tuple[str, ...]
    wake_models: tuple[str, ...]
    wake_model_paths: tuple[str, ...]
    wake_phrase_by_model: dict[str, str]
    wake_word_threshold: float
    wake_word_cooldown_s: float
    vad_positive_speech_threshold: float
    vad_negative_speech_threshold: float
    vad_min_speech_ms: int
    vad_redemption_ms: int
    vad_pre_speech_pad_ms: int
    sample_rate: int
    chunk_ms: int
    mic_device_index: int | None
    ding_wav_path: str
    ding_volume: float
    tts_volume: float
    models_dir: str
    health_poll_interval_s: float
    health_poll_timeout_s: float
    socket_reconnect_attempts: int
    socket_reconnect_delay_s: float
    log_level: str
    log_audio_payloads: bool


def _build_runtime() -> RuntimeSettings:
    here = Path(__file__).resolve().parent
    default_ding = (here / ".." / "assets" / "ding.wav").resolve()
    models_dir_path = Path(
        _optional("MODELS_DIR", str((here / ".." / "models").resolve()))
    ).expanduser().resolve()
    models_dir_path.mkdir(parents=True, exist_ok=True)

    shared_config_path = _resolve_shared_config_path()
    shared_config, voice_daemon_config = _seed_or_load_voice_daemon_config(shared_config_path)

    wake_phrases = _coerce_config_list(
        voice_daemon_config.get("wake_phrases"),
        field_name=f"{VOICE_DAEMON_SECTION}.wake_phrases",
    )
    wake_models = _coerce_config_list(
        voice_daemon_config.get("wake_models"),
        field_name=f"{VOICE_DAEMON_SECTION}.wake_models",
    )

    if len(wake_phrases) != len(wake_models):
        raise RuntimeError(
            "[voice_daemon] Shared config wake_phrases and wake_models must have the same length."
        )

    wake_word_threshold = _coerce_float(
        voice_daemon_config.get("wake_threshold"),
        field_name=f"{VOICE_DAEMON_SECTION}.wake_threshold",
    )
    wake_word_cooldown_s = _coerce_float(
        voice_daemon_config.get("wake_cooldown_s"),
        field_name=f"{VOICE_DAEMON_SECTION}.wake_cooldown_s",
    )

    wake_model_paths = tuple(
        str(_resolve_wake_model_path(model_name, models_dir_path))
        for model_name in wake_models
    )
    wake_phrase_by_model = {
        Path(path).stem: phrase for phrase, path in zip(wake_phrases, wake_model_paths)
    }

    return RuntimeSettings(
        env_path=_ENV_PATH,
        shared_config_path=shared_config_path,
        shared_config=shared_config,
        voice_daemon_config=voice_daemon_config,
        server_url=_optional("SPARK_SERVER_URL", "http://127.0.0.1:8000"),
        daemon_service_token=_require("DAEMON_SERVICE_TOKEN"),
        wake_phrases=wake_phrases,
        wake_models=wake_models,
        wake_model_paths=wake_model_paths,
        wake_phrase_by_model=wake_phrase_by_model,
        wake_word_threshold=wake_word_threshold,
        wake_word_cooldown_s=wake_word_cooldown_s,
        vad_positive_speech_threshold=float(
            _optional("VAD_POSITIVE_SPEECH_THRESHOLD", "0.75")
        ),
        vad_negative_speech_threshold=float(
            _optional("VAD_NEGATIVE_SPEECH_THRESHOLD", "0.55")
        ),
        vad_min_speech_ms=int(_optional("VAD_MIN_SPEECH_MS", "500")),
        vad_redemption_ms=int(_optional("VAD_REDEMPTION_MS", "400")),
        vad_pre_speech_pad_ms=int(_optional("VAD_PRE_SPEECH_PAD_MS", "120")),
        sample_rate=int(_optional("SAMPLE_RATE", "16000")),
        chunk_ms=int(_optional("CHUNK_MS", "20")),
        mic_device_index=(
            int(_optional("MIC_DEVICE_INDEX"))
            if _optional("MIC_DEVICE_INDEX")
            else None
        ),
        ding_wav_path=_optional("DING_WAV_PATH", str(default_ding)),
        ding_volume=float(_optional("DING_VOLUME", "1.0")),
        tts_volume=float(_optional("TTS_VOLUME", "1.0")),
        models_dir=str(models_dir_path),
        health_poll_interval_s=float(_optional("HEALTH_POLL_INTERVAL_S", "1.0")),
        health_poll_timeout_s=float(_optional("HEALTH_POLL_TIMEOUT_S", "60.0")),
        socket_reconnect_attempts=int(_optional("SOCKET_RECONNECT_ATTEMPTS", "0")),
        socket_reconnect_delay_s=float(_optional("SOCKET_RECONNECT_DELAY_S", "2.0")),
        log_level=_optional("LOG_LEVEL", "INFO").upper(),
        log_audio_payloads=_optional("LOG_AUDIO_PAYLOADS", "false").lower() == "true",
    )


def get_wake_phrase_display() -> str:
    if len(WAKE_WORD_PHRASES) == 1:
        return WAKE_WORD_PHRASES[0]
    if len(WAKE_WORD_PHRASES) == 2:
        return f"{WAKE_WORD_PHRASES[0]} or {WAKE_WORD_PHRASES[1]}"
    return ", ".join(WAKE_WORD_PHRASES[:-1]) + f", or {WAKE_WORD_PHRASES[-1]}"


def reload() -> RuntimeSettings:
    runtime = _build_runtime()

    if not (0.0 < runtime.wake_word_threshold <= 1.0):
        raise RuntimeError(
            f"WAKE_WORD_THRESHOLD must be in (0, 1], got {runtime.wake_word_threshold}"
        )

    if runtime.wake_word_cooldown_s < 0.0:
        raise RuntimeError(
            f"WAKE_WORD_COOLDOWN_S must be >= 0, got {runtime.wake_word_cooldown_s}"
        )

    if runtime.vad_positive_speech_threshold <= runtime.vad_negative_speech_threshold:
        raise RuntimeError(
            f"VAD_POSITIVE_SPEECH_THRESHOLD ({runtime.vad_positive_speech_threshold}) "
            f"must be > VAD_NEGATIVE_SPEECH_THRESHOLD ({runtime.vad_negative_speech_threshold})"
        )

    globals()["RUNTIME"] = runtime
    globals()["ENV_PATH"] = runtime.env_path
    globals()["SHARED_CONFIG_PATH"] = runtime.shared_config_path
    globals()["SHARED_CONFIG"] = runtime.shared_config
    globals()["VOICE_DAEMON_CONFIG"] = runtime.voice_daemon_config
    globals()["SERVER_URL"] = runtime.server_url
    globals()["DAEMON_SERVICE_TOKEN"] = runtime.daemon_service_token
    globals()["WAKE_WORD_PHRASES"] = runtime.wake_phrases
    globals()["WAKE_WORD_MODELS"] = runtime.wake_models
    globals()["WAKE_WORD_MODEL_PATHS"] = runtime.wake_model_paths
    globals()["WAKE_WORD_PHRASE_BY_MODEL"] = runtime.wake_phrase_by_model
    globals()["WAKE_WORD_THRESHOLD"] = runtime.wake_word_threshold
    globals()["WAKE_WORD_COOLDOWN_S"] = runtime.wake_word_cooldown_s
    globals()["VAD_POSITIVE_SPEECH_THRESHOLD"] = runtime.vad_positive_speech_threshold
    globals()["VAD_NEGATIVE_SPEECH_THRESHOLD"] = runtime.vad_negative_speech_threshold
    globals()["VAD_MIN_SPEECH_MS"] = runtime.vad_min_speech_ms
    globals()["VAD_REDEMPTION_MS"] = runtime.vad_redemption_ms
    globals()["VAD_PRE_SPEECH_PAD_MS"] = runtime.vad_pre_speech_pad_ms
    globals()["SAMPLE_RATE"] = runtime.sample_rate
    globals()["CHUNK_MS"] = runtime.chunk_ms
    globals()["MIC_DEVICE_INDEX"] = runtime.mic_device_index
    globals()["DING_WAV_PATH"] = runtime.ding_wav_path
    globals()["DING_VOLUME"] = runtime.ding_volume
    globals()["TTS_VOLUME"] = runtime.tts_volume
    globals()["MODELS_DIR"] = runtime.models_dir
    globals()["HEALTH_POLL_INTERVAL_S"] = runtime.health_poll_interval_s
    globals()["HEALTH_POLL_TIMEOUT_S"] = runtime.health_poll_timeout_s
    globals()["SOCKET_RECONNECT_ATTEMPTS"] = runtime.socket_reconnect_attempts
    globals()["SOCKET_RECONNECT_DELAY_S"] = runtime.socket_reconnect_delay_s
    globals()["LOG_LEVEL"] = runtime.log_level
    globals()["LOG_AUDIO_PAYLOADS"] = runtime.log_audio_payloads
    return runtime


reload()
