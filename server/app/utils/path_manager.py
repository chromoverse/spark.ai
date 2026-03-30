import os
import platform
import sys
from pathlib import Path
from typing import Optional


class PathManager:
    """
    Centralized path manager for Jarvis.
    Resolves user data, model paths, redis URL, and bundle locations
    dynamically depending on OS and whether server is frozen.
    Always uses Local paths (not Roaming).
    """

    def __init__(self, env: Optional[dict] = None):
        """
        env: dictionary of environment variables from Electron spawn
        """
        self.env = env or os.environ
        self.system = platform.system()
        self._setup_paths()

    def _get_meipass(self) -> Path:
        """Return PyInstaller _MEIPASS or current directory."""
        return Path(getattr(sys, "_MEIPASS", "."))

    def _resolve_server_dir(self) -> Path:
        """Resolve the bundled or local server root that owns the tools package."""
        override = self.env.get("JARVIS_SERVER_DIR")
        if override:
            return Path(override)

        if getattr(sys, "frozen", False):
            candidates = (
                self.BUNDLE_DIR / "server",
                self.BUNDLE_DIR,
                Path(sys.executable).resolve().parent / "server",
            )
        else:
            candidates = (Path(__file__).resolve().parents[2],)

        for candidate in candidates:
            if (candidate / "app").exists() and (candidate / "tools").exists():
                return candidate

        return candidates[0]

    def _default_user_data_dir(self) -> Path:
        """Determine OS-specific writable user data directory (Local)."""
        if self.system == "Windows":
            return Path.home() / "AppData" / "Local" / "SparkAI"
        elif self.system == "Darwin":
            return Path.home() / "Library" / "Application Support" / "SparkAI"
        else:
            # Linux / Unix
            return Path.home() / ".local" / "share" / "SparkAI"

    def _setup_paths(self):
        # Bundle / frozen paths
        if getattr(sys, "frozen", False):
            self.BUNDLE_DIR = self._get_meipass()
            self.EXE_DIR = Path(sys.executable).parent
        else:
            self.BUNDLE_DIR = Path(__file__).parent
            self.EXE_DIR = None

        # User Data directory (Local for everything)
        self.USER_DATA_DIR = Path(self.env.get("JARVIS_DATA_DIR", self._default_user_data_dir()))
        self.USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

        # Models directory
        self.MODELS_DIR = Path(self.env.get("JARVIS_MODELS_DIR", self.USER_DATA_DIR / "models"))
        self.MODELS_DIR.mkdir(parents=True, exist_ok=True)

        # Redis URL
        self.REDIS_URL = self.env.get("JARVIS_REDIS_URL", "redis://127.0.0.1:6379")

        # Config / logs / memory folders
        self.CONFIG_FILE = self.USER_DATA_DIR / "config.json"
        self.LOGS_DIR = self.USER_DATA_DIR / "logs"
        self.MEMORY_DIR = self.USER_DATA_DIR / "memory"
        self.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        self.MEMORY_DIR.mkdir(parents=True, exist_ok=True)

        # Bundled/local server resources
        self.SERVER_DIR = self._resolve_server_dir()
        self.TOOLS_DIR = Path(self.env.get("JARVIS_TOOLS_DIR", self.SERVER_DIR / "tools"))
        self.TOOLS_MANIFEST_FILE = self.TOOLS_DIR / "manifest.json"
        self.TOOLS_REGISTRY_FILE = self.TOOLS_DIR / "registry" / "tool_registry.json"
        self.TOOLS_INDEX_FILE = self.TOOLS_DIR / "registry" / "tool_index.json"

    # Accessors
    def get_bundle_dir(self) -> Path:
        return self.BUNDLE_DIR

    def get_exe_dir(self) -> Optional[Path]:
        return self.EXE_DIR

    def get_server_dir(self) -> Path:
        return self.SERVER_DIR

    def get_user_data_dir(self) -> Path:
        return self.USER_DATA_DIR

    def get_models_dir(self) -> Path:
        return self.MODELS_DIR

    def get_redis_url(self) -> str:
        return self.REDIS_URL

    def get_logs_dir(self) -> Path:
        return self.LOGS_DIR

    def get_memory_dir(self) -> Path:
        return self.MEMORY_DIR

    def get_config_file(self) -> Path:
        return self.CONFIG_FILE

    def get_tools_dir(self) -> Path:
        return self.TOOLS_DIR

    def get_tools_registry_file(self) -> Path:
        return self.TOOLS_REGISTRY_FILE

    def get_tools_manifest_file(self) -> Path:
        return self.TOOLS_MANIFEST_FILE

    def get_tools_index_file(self) -> Path:
        return self.TOOLS_INDEX_FILE
