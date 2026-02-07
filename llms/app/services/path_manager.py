"""
Path Manager Service
--------------------
Centralized path resolution for the application.
Handles OS-specific paths and PyInstaller frozen mode.

Paths Managed:
    - User data directory (AppData/Local on Windows)
    - Models directory
    - Binaries directory (for llama.cpp)
    - Logs and config directories
"""

import os
import platform
import sys
from pathlib import Path
from typing import Optional


class PathManager:
    """
    Centralized path manager for the Reasoning LLM service.
    
    Key Features:
        - OS-specific user data directories
        - PyInstaller frozen mode support
        - Environment variable overrides for Electron integration
    
    Usage:
        path_mgr = PathManager()
        models_dir = path_mgr.get_models_dir()
    """

    # Application name for data directories
    APP_NAME = "SparkAI"

    def __init__(self, env: Optional[dict] = None):
        """
        Initialize path manager.
        
        Args:
            env: Custom environment dict (defaults to os.environ)
        """
        self.env = env or os.environ
        self.system = platform.system()
        self._setup_paths()

    def _get_meipass(self) -> Path:
        """
        Get PyInstaller _MEIPASS directory.
        
        Returns:
            Path to temp extraction dir in frozen mode,
            or current directory in development.
        """
        return Path(getattr(sys, "_MEIPASS", "."))

    def _default_user_data_dir(self) -> Path:
        """
        Get OS-specific user data directory.
        Uses Local (not Roaming) on Windows for better performance.
        
        Returns:
            Path to user data directory
        """
        if self.system == "Windows":
            return Path.home() / "AppData" / "Local" / self.APP_NAME
        elif self.system == "Darwin":  # macOS
            return Path.home() / "Library" / "Application Support" / self.APP_NAME
        else:  # Linux/Unix
            return Path.home() / ".local" / "share" / self.APP_NAME

    def _setup_paths(self):
        """Initialize all path attributes."""
        
        # -----------------------
        # Bundle/Executable Paths
        # -----------------------
        if getattr(sys, "frozen", False):
            # PyInstaller frozen mode
            self.BUNDLE_DIR = self._get_meipass()
            self.EXE_DIR = Path(sys.executable).parent
        else:
            # Development mode
            self.BUNDLE_DIR = Path(__file__).parent.parent.parent
            self.EXE_DIR = None

        # -----------------------
        # User Data Directory
        # -----------------------
        self.USER_DATA_DIR = Path(
            self.env.get("JARVIS_DATA_DIR", self._default_user_data_dir())
        )
        self.USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

        # -----------------------
        # Models Directory
        # -----------------------
        self.MODELS_DIR = Path(
            self.env.get("JARVIS_MODELS_DIR", self.USER_DATA_DIR / "models")
        )
        self.MODELS_DIR.mkdir(parents=True, exist_ok=True)

        # -----------------------
        # Binaries Directory (llama.cpp)
        # -----------------------
        self.BINARIES_DIR = self.USER_DATA_DIR / "binaries"
        self.BINARIES_DIR.mkdir(parents=True, exist_ok=True)

        # -----------------------
        # Config/Logs Directories
        # -----------------------
        self.CONFIG_FILE = self.USER_DATA_DIR / "config.json"
        self.LOGS_DIR = self.USER_DATA_DIR / "logs"
        self.LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # -----------------------
    # Public Accessors
    # -----------------------
    
    def get_bundle_dir(self) -> Path:
        """Get bundle directory (source in dev, _MEIPASS in frozen)."""
        return self.BUNDLE_DIR

    def get_exe_dir(self) -> Optional[Path]:
        """Get executable directory (only in frozen mode)."""
        return self.EXE_DIR

    def get_user_data_dir(self) -> Path:
        """Get user data directory (AppData/Local/SparkAI on Windows)."""
        return self.USER_DATA_DIR

    def get_models_dir(self) -> Path:
        """Get models directory for LLM model files."""
        return self.MODELS_DIR

    def get_binaries_dir(self) -> Path:
        """Get binaries directory for llama.cpp executables."""
        return self.BINARIES_DIR

    def get_logs_dir(self) -> Path:
        """Get logs directory."""
        return self.LOGS_DIR

    def get_config_file(self) -> Path:
        """Get path to user config file."""
        return self.CONFIG_FILE


# -----------------------
# Singleton Instance
# -----------------------
_path_manager: Optional[PathManager] = None


def get_path_manager() -> PathManager:
    """
    Get singleton PathManager instance.
    
    Returns:
        PathManager singleton
    """
    global _path_manager
    if _path_manager is None:
        _path_manager = PathManager()
    return _path_manager
