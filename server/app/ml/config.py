"""
ML Configuration
Centralized configuration for all ML models
"""
from app.ml.device_profile import detect_device_profile

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
        "name": "BAAI/bge-m3",
        "path": MODELS_DIR / "bge-m3",
        "type": "sentence-transformer",
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

# Unified device detection (shared with runtime dependency bootstrap)
DEVICE_PROFILE = detect_device_profile()
DEVICE = DEVICE_PROFILE.device
for model_config in MODELS_CONFIG.values():
    model_config["device"] = DEVICE

# Worker settings
WORKER_SETTINGS = {
    "max_workers": 4,
    "queue_size": 100,
    "timeout": 30,
}
