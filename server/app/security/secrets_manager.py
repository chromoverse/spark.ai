"""
Secrets Manager - Load and manage application secrets.

Priority order:
1. User's .env in AppData (if exists) - allows override
2. Encrypted defaults bundled with app
3. Development .env (when running from source)

Note: Any new keys added to .env will be automatically included
when you rebuild the exe (via encrypt_secrets.py).
"""
from __future__ import annotations
import sys
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from dotenv import dotenv_values

from app.security.crypto import decrypt_dict

logger = logging.getLogger(__name__)

# Path to encrypted defaults (bundled with app)
_ENCRYPTED_DEFAULTS_FILE = "encrypted_defaults.json"


def _get_meipass() -> Path:
    """Get PyInstaller's _MEIPASS or current directory."""
    return Path(getattr(sys, '_MEIPASS', '.'))


class SecretsManager:
    """Manages loading and decrypting application secrets."""
    
    _instance: Optional[SecretsManager] = None
    _secrets: Dict[str, Any] = {}
    _loaded = False
    
    def __new__(cls) -> SecretsManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self) -> None:
        if not self._loaded:
            self._load_secrets()
            SecretsManager._loaded = True
    
    def _get_bundle_dir(self) -> Path:
        """Get PyInstaller bundle directory or project root."""
        if getattr(sys, 'frozen', False):
            return _get_meipass()
        return Path(__file__).resolve().parent.parent.parent
    
    def _get_user_data_dir(self) -> Path:
        """Get user data directory (AppData on Windows)."""
        if getattr(sys, 'frozen', False):
            return Path.home() / "AppData" / "Local" / "SparkAI"
        return self._get_bundle_dir()
    
    def _load_secrets(self) -> None:
        """Load secrets from available sources."""
        bundle_dir = self._get_bundle_dir()
        user_data_dir = self._get_user_data_dir()
        
        # 1. Try to load encrypted defaults from bundle
        encrypted_path = bundle_dir / _ENCRYPTED_DEFAULTS_FILE
        if encrypted_path.exists():
            try:
                with open(encrypted_path, 'r', encoding='utf-8') as f:
                    encrypted_data = json.load(f)
                self._secrets = decrypt_dict(encrypted_data)
                logger.info("✅ Loaded encrypted defaults from bundle")
            except Exception as e:
                logger.warning(f"⚠️ Failed to load encrypted defaults: {e}")
        
        # 2. Load development .env (if running from source)
        if not getattr(sys, 'frozen', False):
            dev_env = bundle_dir / ".env"
            if dev_env.exists():
                env_values = dotenv_values(dev_env)
                self._secrets.update(env_values)  # type: ignore[arg-type]
                logger.info("✅ Loaded development .env")
        
        # 3. Override with user's AppData/.env if exists
        user_env = user_data_dir / ".env"
        if user_env.exists():
            env_values = dotenv_values(user_env)
            self._secrets.update(env_values)  # type: ignore[arg-type]
            logger.info(f"✅ Loaded user overrides from {user_env}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a secret value."""
        return self._secrets.get(key, default)
    
    def get_all(self) -> Dict[str, Any]:
        """Get all secrets (for Settings initialization)."""
        return self._secrets.copy()
    
    def __getitem__(self, key: str) -> Any:
        return self._secrets[key]
    
    def __contains__(self, key: str) -> bool:
        return key in self._secrets


# Singleton accessor
def get_secrets() -> SecretsManager:
    """Get the secrets manager instance."""
    return SecretsManager()
