"""
ML Configuration — single source of truth for all model metadata.

Load flags (per model)
──────────────────────
  load: True   — eager load on startup via load_all_models()
  load: False  — skip on startup

  lazy_load: True  — load on first get_model() call (load=False required)
  lazy_load: False — never load automatically; must call load_model() explicitly

Common patterns:
  load=True,  lazy_load=False  → always loaded at boot (embedding, whisper)
  load=False, lazy_load=True   → loaded on first use, then cached (emotion)
  load=False, lazy_load=False  → disabled; get_model() returns None (unused models)

Device tiers
────────────
CPU / Vulkan  →  google/gemma-embedding-300m   (~300 M params, 768-dim)
CUDA          →  BAAI/bge-base-en-v1.5          (109 M params, 768-dim, GPU-optimised)

Both tiers produce 768-dim vectors so the LanceDB schema never needs rebuilding
when switching between devices.
"""

from typing import Optional
from app.ml.device_profile import DeviceProfile, detect_device_profile
from app.utils.path_manager import PathManager

_pm = PathManager()
MODELS_DIR = _pm.get_models_dir()
MODELS_DIR.mkdir(parents=True, exist_ok=True)

MODELS_CONFIG = {

    "embedding": {
        # ── CPU / Vulkan ───────────────────────────────────────────────────
        "name_cpu": "google/gemma-embedding-300m",
        "path_cpu": MODELS_DIR / "embedding" / "text" / "embeddinggemma-300m",
        "dim_cpu":  768,
        # ── CUDA ──────────────────────────────────────────────────────────
        "name_gpu": "BAAI/bge-base-en-v1.5",
        "path_gpu": MODELS_DIR / "embedding" / "text" / "bge-base-en-v1.5",
        "dim_gpu":  768,
        # ── Resolved at runtime ───────────────────────────────────────────
        "name":      None,
        "path":      None,
        "dimension": 768,

        "type":           "sentence-transformer",
        "device":         "auto",
        "batch_size":     32,
        "max_seq_length": 512,

        # ── Load policy ───────────────────────────────────────────────────
        "load":      True,    # eager — must be ready before any RAG query
        "lazy_load": False,
    },

    "whisper": {
        # SYSTRAN/faster-whisper-small — multilingual (en/hi/ne), INT8 on CPU
        # beam_size=1 and vad_filter=False set in stt_services (VAD is upstream)
        "name":   "SYSTRAN/faster-whisper-small",
        "path":   MODELS_DIR / "whisper",
        "type":   "whisper",
        "device": "auto",

        # ── Load policy ───────────────────────────────────────────────────
        "load":      True,    # eager — STT must be hot before first voice query
        "lazy_load": False,
    },

    "emotion": {
        "name":   "j-hartmann/emotion-english-distilroberta-base",
        "path":   MODELS_DIR / "emotion" / "roberta",
        "type":   "transformers",
        "device": "auto",

        # ── Load policy ───────────────────────────────────────────────────
        "load":      False,   # not used right now — skip at boot
        "lazy_load": True,    # will load on first get_model("emotion") call
    },
}


# ── Device helpers ─────────────────────────────────────────────────────────────

_cached_profile: Optional[DeviceProfile] = None


def get_device_profile(force: bool = False) -> DeviceProfile:
    global _cached_profile
    if force or _cached_profile is None:
        _cached_profile = detect_device_profile()
    return _cached_profile


def get_device(force: bool = False) -> str:
    return get_device_profile(force=force).device


def apply_runtime_device_to_models(force: bool = False) -> str:
    """
    Resolve device once and stamp every model config with the correct
    name / path / dimension / device for the current hardware.
    Called exactly once by ModelLoader._ensure_device().
    """
    device = get_device(force=force)
    is_gpu = device in ("cuda", "mps")

    for cfg in MODELS_CONFIG.values():
        cfg["device"] = device
        if "name_cpu" in cfg:
            cfg["name"]      = cfg["name_gpu"] if is_gpu else cfg["name_cpu"]
            cfg["path"]      = cfg["path_gpu"] if is_gpu else cfg["path_cpu"]
            cfg["dimension"] = cfg["dim_gpu"]  if is_gpu else cfg["dim_cpu"]

    return device


# ── Worker settings ────────────────────────────────────────────────────────────

WORKER_SETTINGS = {
    "max_workers": 4,
    "queue_size":  100,
    "timeout":     30,
}