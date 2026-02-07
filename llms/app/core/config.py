"""
Application Configuration Module
---------------------------------
Centralized configuration using Pydantic Settings.
Loads from environment variables with sensible defaults.

Environment Variables:
    - HOST: Server host (default: 0.0.0.0)
    - PORT: Server port (default: 8000)
    - DEBUG: Enable debug mode (default: false)
    - MODEL_NAME: LLM model to use (default: qwen2.5-7b)
    - MAX_TOKENS: Default max tokens (default: 512)
    - TEMPERATURE: Default temperature (default: 0.7)
"""

from pydantic_settings import BaseSettings
from typing import Optional
from pathlib import Path


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    Designed for easy configuration in Docker/Electron environments.
    """
    
    # ---------------------
    # Server Configuration
    # ---------------------
    host: str = "0.0.0.0"
    port: int = 9001
    debug: bool = False
    
    # ---------------------
    # Model Configuration  
    # ---------------------
    # RECOMMENDED: qwen2.5-coder-1.5b for JSON output (follows instructions precisely)
    # Other options: smollm2-1.7b, llama-3.2-1b, qwen2.5-1.5b
    model_name: str = "qwen2.5-coder-1.5b"  # Best for structured JSON output
    max_tokens: int = 512           # Default max tokens for generation
    temperature: float = 0.1        # Low temp for deterministic JSON (0.1-0.3 recommended)
    
    # ---------------------
    # Path Configuration
    # ---------------------
    # These can be overridden via environment for Electron integration
    data_dir: Optional[str] = None      # Override for JARVIS_DATA_DIR
    models_dir: Optional[str] = None    # Override for JARVIS_MODELS_DIR
    
    # ---------------------
    # Feature Flags
    # ---------------------
    auto_download_model: bool = True     # Auto-download model if missing
    auto_download_binary: bool = True    # Auto-download llama.cpp if missing
    warmup_on_startup: bool = False      # Warmup model on server start (slow on CPU)
    
    class Config:
        env_prefix = ""  # No prefix, use direct env var names
        case_sensitive = False


# ---------------------
# Singleton Instance
# ---------------------
settings = Settings()


def get_project_root() -> Path:
    """
    Get the project root directory.
    Works both in development and PyInstaller frozen mode.
    """
    import sys
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller bundle
        return Path(sys.executable).parent
    else:
        # Development mode - go up from app/core/config.py
        return Path(__file__).parent.parent.parent


def get_config_path() -> Path:
    """Get path to model_config.json"""
    return get_project_root() / "model_config.json"
