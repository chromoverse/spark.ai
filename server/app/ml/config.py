"""
ML Configuration
Centralized configuration for all ML models
"""
import os
from pathlib import Path

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent
MODELS_DIR = BASE_DIR / "models"

# Ensure models directory exists
MODELS_DIR.mkdir(exist_ok=True)

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
        "name": "openai/whisper-small",
        "path": MODELS_DIR / "whisper-small",
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
    "openaudio_s1_mini": {
    "name": "fishaudio/openaudio-s1-mini",
    "path": MODELS_DIR / "openaudio-s1-mini",
    "type": "fishaudio",
    "device": "auto",
    }
}

# GPU/Device detection
def get_optimal_device():
    """Detect the best available device"""
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"

# Set device for all models
DEVICE = get_optimal_device()
for model_config in MODELS_CONFIG.values():
    model_config["device"] = DEVICE

# Worker settings
WORKER_SETTINGS = {
    "max_workers": 4,
    "queue_size": 100,
    "timeout": 30,
}