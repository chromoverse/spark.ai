"""
ML Configuration
Centralized configuration for all ML models
"""
from typing import Optional

from app.ml.device_profile import DeviceProfile, detect_device_profile

# Base paths
from app.utils.path_manager import PathManager

# Initialize PathManager
path_manager = PathManager()
MODELS_DIR = path_manager.get_models_dir()

# Ensure models directory exists
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# Model configurations
MODELS_CONFIG = {
    "embedding": {
        "name": "BAAI/bge-base-en-v1.5",
        "path": MODELS_DIR / "bge-base-en-v1.5",
        "type": "sentence-transformer",
        "dimension": 768,
        "device": "auto",  # Will be set to cuda/mps/cpu dynamically
        "batch_size": 32,
        "max_seq_length": 512,
    },
    "whisper": {
        "name": "openai/whisper-base.en",
        "path": MODELS_DIR / "whisper-base.en",
        "type": "whisper",
        "device": "auto",
        "compute_type": "float16",  # or int8 for CPU
    },
    "emotion": {
        "name": "j-hartmann/emotion-english-distilroberta-base",
        "path": MODELS_DIR / "emotion-roberta",
        "type": "transformers",
        "device": "auto",
    },
}

_CACHED_DEVICE_PROFILE: Optional[DeviceProfile] = None


def get_device_profile(force_refresh: bool = False) -> DeviceProfile:
    """
    Lazily resolve and cache device profile.
    We intentionally avoid eager torch probing at module import time.
    """
    global _CACHED_DEVICE_PROFILE
    if force_refresh or _CACHED_DEVICE_PROFILE is None:
        _CACHED_DEVICE_PROFILE = detect_device_profile()
    return _CACHED_DEVICE_PROFILE


def get_device(force_refresh: bool = False) -> str:
    """Return cached runtime device string: cuda | mps | cpu."""
    return get_device_profile(force_refresh=force_refresh).device


def apply_runtime_device_to_models(force_refresh: bool = False) -> str:
    """
    Resolve device once and stamp all model configs.
    Called by model loader on first local runtime load.
    """
    device = get_device(force_refresh=force_refresh)
    for model_config in MODELS_CONFIG.values():
        model_config["device"] = device
    return device

# Worker settings
WORKER_SETTINGS = {
    "max_workers": 4,
    "queue_size": 100,
    "timeout": 30,
}
