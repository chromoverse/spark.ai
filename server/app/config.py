"""
Spark.AI Configuration
======================
Centralized configuration and path management for the server.

Secrets are loaded from:
1. Encrypted defaults bundled with exe (for production)
2. Development .env (when running from source)
3. User override from AppData/.env (optional)
"""
from __future__ import annotations
import sys
import os
from pathlib import Path
from typing import Any, TYPE_CHECKING

# pydantic_settings is installed but Pylance may not find it in some envs
try:
    from pydantic_settings import BaseSettings
except ImportError:
    # Fallback for type checking
    from pydantic import BaseModel as BaseSettings  # type: ignore

# -----------------------------------------------------------------------------
# Path Management
# -----------------------------------------------------------------------------

def _get_meipass() -> Path:
    """Get PyInstaller's _MEIPASS or current directory."""
    # sys._MEIPASS is added by PyInstaller at runtime
    return Path(getattr(sys, '_MEIPASS', '.'))

if getattr(sys, 'frozen', False):
    # Production (Frozen/Bundled)
    BUNDLE_DIR = _get_meipass()
    USER_DATA_DIR = Path.home() / "AppData" / "Local" / "SparkAI"
    EXE_DIR = Path(sys.executable).parent
else:
    # Development
    BUNDLE_DIR = Path(__file__).resolve().parent.parent
    USER_DATA_DIR = BUNDLE_DIR
    EXE_DIR = BUNDLE_DIR

# Ensure User Data directory exists
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

# -----------------------------------------------------------------------------
# Load Secrets (Encrypted in production, plain in development)
# -----------------------------------------------------------------------------

from app.security import get_secrets
_secrets = get_secrets()

# -----------------------------------------------------------------------------
# Settings
# -----------------------------------------------------------------------------

class Settings(BaseSettings):  # type: ignore[misc]
    """Application settings with defaults from encrypted secrets."""
    
    # LLM Models
    gemini_model_name: str = "gemini-2.5-flash"
    openrouter_light_model_name: str = "mistralai/mistral-7b-instruct"
    openrouter_reasoning_model_name: str = "meta-llama/llama-3.3-70b-instruct"
    
    # Server
    port: int = 8000
    
    # AI Config
    ai_name: str = "SPARK"
    default_lang: str = "en"
    word_matching_threshold: float = 0.35
    environment: str = "production"
    db_name: str = "spark"
    
    # Voice defaults
    nep_voice_male: str = "ne-NP-SagarNeural"
    nep_voice_female: str = "ne-NP-HemkalaNeural"
    hindi_voice_male: str = "hi-IN-MadhurNeural"
    hindi_voice_female: str = "hi-IN-SwaraNeural"
    eng_voice_male: str = "en-US-BrianNeural"
    eng_voice_female: str = "en-US-JennyNeural"
    
    # API Keys (loaded from encrypted secrets - any key in .env is auto-loaded)
    openrouter_api_key: str = ""
    gemini_api_key: str = ""
    ELEVEN_LABS_API_KEY: str = ""
    pinecone_api_key: str = ""
    pinecone_env: str = ""
    pinecone_index_name: str = ""
    pinecone_metadata_namespace: str = ""
    mongo_uri: str = ""
    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""
    HUGGINGFACE_API_ACCESS_TOKEN: str = ""
    
    def __init__(self, **kwargs: Any):
        # Merge secrets into kwargs (secrets override defaults)
        all_secrets = _secrets.get_all()
        
        # Convert secret keys to lowercase for pydantic matching
        normalized: dict[str, Any] = {}
        for key, value in all_secrets.items():
            normalized[key.lower()] = value
        
        # User-provided kwargs override secrets
        normalized.update(kwargs)
        
        super().__init__(**normalized)
    
    class Config:
        extra = "ignore"


# Singleton settings instance
settings = Settings()