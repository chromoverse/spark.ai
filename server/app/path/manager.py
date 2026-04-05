"""Central path allocation for the server runtime.

The grouped layout objects below make it obvious which directory is used for
which purpose. Older uppercase attributes are still exposed for compatibility,
but new code should prefer `layout`, `get_runtime_paths()`, `get_artifact_paths()`,
and `get_tool_paths()` because they read more cleanly.
"""

from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class RuntimePaths:
    """Server-owned state that lives directly under the user data root."""

    root: Path
    config_file: Path
    logs_dir: Path
    memory_dir: Path


@dataclass(frozen=True)
class ArtifactPaths:
    """Durable artifact storage produced by tools (screenshots, documents, etc.)."""

    root: Path
    records_dir: Path
    screenshots_dir: Path
    documents_dir: Path
    exports_dir: Path
    media_dir: Path


@dataclass(frozen=True)
class ToolPaths:
    """Tool metadata files. The registry is authored; index/manifest are derived."""

    root: Path
    manifest_file: Path
    registry_file: Path
    index_file: Path


@dataclass(frozen=True)
class PathLayout:
    """Readable grouped view of every important server path."""

    bundle_dir: Path
    exe_dir: Optional[Path]
    server_dir: Path
    user_data_dir: Path
    models_dir: Path
    db_dir: Path
    binaries_dir: Path
    runtime: RuntimePaths
    artifacts: ArtifactPaths
    tools: ToolPaths


class PathManager:
    """
    Canonical path service for the server/runtime.

    The `layout` object is the preferred way to inspect where things live.
    Older attributes such as `USER_DATA_DIR` and `TOOLS_DIR` remain available
    so existing code does not break while we migrate.
    """

    def __init__(self, env: Optional[dict] = None):
        self.env = env or os.environ
        self.system = platform.system()
        self.layout: PathLayout
        self._requested_user_data_dir: Path
        self._fallback_user_data_dir: Path
        self._using_fallback_user_data_dir = False
        self._setup_paths()

    def _get_meipass(self) -> Path:
        return Path(getattr(sys, "_MEIPASS", "."))

    def _resolve_server_dir(self, bundle_dir: Path) -> Path:
        override = self.env.get("JARVIS_SERVER_DIR")
        if override:
            return Path(override)

        if getattr(sys, "frozen", False):
            candidates = (
                bundle_dir / "server",
                bundle_dir,
                Path(sys.executable).resolve().parent / "server",
            )
        else:
            candidates = (Path(__file__).resolve().parents[2],)

        for candidate in candidates:
            if (candidate / "app").exists() and (candidate / "tools").exists():
                return candidate

        return candidates[0]

    def _default_user_data_dir(self) -> Path:
        if self.system == "Windows":
            return Path.home() / "AppData" / "Local" / "SparkAI"
        if self.system == "Darwin":
            return Path.home() / "Library" / "Application Support" / "SparkAI"
        return Path.home() / ".local" / "share" / "SparkAI"

    def _setup_paths(self) -> None:
        if getattr(sys, "frozen", False):
            bundle_dir = self._get_meipass()
            exe_dir = Path(sys.executable).parent
        else:
            bundle_dir = Path(__file__).resolve().parents[2]
            exe_dir = None

        requested_user_data_dir = Path(
            self.env.get("JARVIS_DATA_DIR", self._default_user_data_dir())
        )
        fallback_user_data_dir = bundle_dir / ".sparkai_data"
        user_data_dir = self._ensure_writable_dir(
            requested_user_data_dir,
            fallback_user_data_dir,
        )
        self._requested_user_data_dir = requested_user_data_dir
        self._fallback_user_data_dir = fallback_user_data_dir
        self._using_fallback_user_data_dir = (
            user_data_dir.resolve() == fallback_user_data_dir.resolve()
        )
        models_dir = self._ensure_writable_dir(
            Path(self.env.get("JARVIS_MODELS_DIR", user_data_dir / "models")),
            user_data_dir / "models",
        )
        server_dir = self._resolve_server_dir(bundle_dir)

        runtime_paths = RuntimePaths(
            root=user_data_dir,
            config_file=user_data_dir / "config.json",
            logs_dir=self._ensure_writable_dir(user_data_dir / "logs", user_data_dir / "logs"),
            memory_dir=self._ensure_writable_dir(user_data_dir / "memory", user_data_dir / "memory"),
        )

        # Artifact directories are grouped so future artifact kinds have one
        # obvious home under the same durable storage root.
        artifacts_root = self._ensure_writable_dir(
            user_data_dir / "artifacts",
            user_data_dir / "artifacts",
        )
        artifact_paths = ArtifactPaths(
            root=artifacts_root,
            records_dir=self._ensure_writable_dir(
                artifacts_root / "records",
                artifacts_root / "records",
            ),
            screenshots_dir=self._ensure_writable_dir(
                artifacts_root / "screenshots",
                artifacts_root / "screenshots",
            ),
            documents_dir=self._ensure_writable_dir(
                artifacts_root / "documents",
                artifacts_root / "documents",
            ),
            exports_dir=self._ensure_writable_dir(
                artifacts_root / "exports",
                artifacts_root / "exports",
            ),
            media_dir=self._ensure_writable_dir(
                artifacts_root / "media",
                artifacts_root / "media",
            ),
        )

        db_dir = self._ensure_writable_dir(
            user_data_dir / "db",
            user_data_dir / "db",
        )
        binaries_dir = self._ensure_writable_dir(
            user_data_dir / "binaries",
            user_data_dir / "binaries",
        )

        tools_root = Path(self.env.get("JARVIS_TOOLS_DIR", server_dir / "tools"))
        tool_paths = ToolPaths(
            root=tools_root,
            manifest_file=tools_root / "manifest.json",
            registry_file=tools_root / "registry" / "tool_registry.json",
            index_file=tools_root / "registry" / "tool_index.json",
        )

        self.layout = PathLayout(
            bundle_dir=bundle_dir,
            exe_dir=exe_dir,
            server_dir=server_dir,
            user_data_dir=user_data_dir,
            models_dir=models_dir,
            db_dir=db_dir,
            binaries_dir=binaries_dir,
            runtime=runtime_paths,
            artifacts=artifact_paths,
            tools=tool_paths,
        )

        self.REDIS_URL = self.env.get("JARVIS_REDIS_URL", "redis://127.0.0.1:6379")

        # Backward-compatible aliases for existing imports.
        self.BUNDLE_DIR = self.layout.bundle_dir
        self.EXE_DIR = self.layout.exe_dir
        self.SERVER_DIR = self.layout.server_dir
        self.USER_DATA_DIR = self.layout.user_data_dir
        self.MODELS_DIR = self.layout.models_dir
        self.CONFIG_FILE = self.layout.runtime.config_file
        self.LOGS_DIR = self.layout.runtime.logs_dir
        self.MEMORY_DIR = self.layout.runtime.memory_dir
        self.ARTIFACTS_DIR = self.layout.artifacts.root
        self.ARTIFACT_RECORDS_DIR = self.layout.artifacts.records_dir
        self.SCREENSHOTS_DIR = self.layout.artifacts.screenshots_dir
        self.DB_DIR = self.layout.db_dir
        self.BINARIES_DIR = self.layout.binaries_dir
        self.TOOLS_DIR = self.layout.tools.root
        self.TOOLS_MANIFEST_FILE = self.layout.tools.manifest_file
        self.TOOLS_REGISTRY_FILE = self.layout.tools.registry_file
        self.TOOLS_INDEX_FILE = self.layout.tools.index_file

    def get_layout(self) -> PathLayout:
        return self.layout

    def get_runtime_paths(self) -> RuntimePaths:
        return self.layout.runtime

    def get_artifact_paths(self) -> ArtifactPaths:
        return self.layout.artifacts

    def get_tool_paths(self) -> ToolPaths:
        return self.layout.tools

    def get_bundle_dir(self) -> Path:
        return self.layout.bundle_dir

    def get_exe_dir(self) -> Optional[Path]:
        return self.layout.exe_dir

    def get_server_dir(self) -> Path:
        return self.layout.server_dir

    def get_user_data_dir(self) -> Path:
        return self.layout.user_data_dir

    def get_requested_user_data_dir(self) -> Path:
        """Return the preferred primary data root before fallback selection."""
        return self._requested_user_data_dir

    def get_fallback_user_data_dir(self) -> Path:
        """Return the repo/bundle fallback root used only when primary is unavailable."""
        return self._fallback_user_data_dir

    def is_using_fallback_user_data_dir(self) -> bool:
        """Expose whether runtime storage currently had to fall back to `.sparkai_data`."""
        return self._using_fallback_user_data_dir

    def get_models_dir(self) -> Path:
        return self.layout.models_dir

    def get_redis_url(self) -> str:
        return self.REDIS_URL

    def get_logs_dir(self) -> Path:
        return self.layout.runtime.logs_dir

    def get_memory_dir(self) -> Path:
        return self.layout.runtime.memory_dir

    def get_config_file(self) -> Path:
        return self.layout.runtime.config_file

    def get_tools_dir(self) -> Path:
        return self.layout.tools.root

    def get_tools_registry_file(self) -> Path:
        return self.layout.tools.registry_file

    def get_tools_manifest_file(self) -> Path:
        return self.layout.tools.manifest_file

    def get_tools_index_file(self) -> Path:
        return self.layout.tools.index_file

    def get_artifacts_dir(self) -> Path:
        return self.layout.artifacts.root

    def get_artifact_records_dir(self) -> Path:
        return self.layout.artifacts.records_dir

    def get_screenshots_dir(self, user_id: str = "shared") -> Path:
        return self.get_artifact_dir("screenshots", user_id=user_id)

    def get_db_dir(self) -> Path:
        return self.layout.db_dir

    def get_binaries_dir(self) -> Path:
        return self.layout.binaries_dir

    def get_artifact_dir(self, kind: str, user_id: str = "shared") -> Path:
        """Return ``artifacts/<kind>/<user_id>/``, creating it if necessary.

        New artifact kinds are auto-created on first access so tools that
        produce a novel kind do not require manual directory setup.
        """
        safe_kind = self._safe_path_token(kind) or "generic"
        safe_user = self._safe_path_token(user_id)
        path = self.layout.artifacts.root / safe_kind / safe_user
        path.mkdir(parents=True, exist_ok=True)
        return path

    def to_user_data_relative_path(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.layout.user_data_dir.resolve()).as_posix()
        except ValueError:
            return path.resolve().as_posix()

    @staticmethod
    def _safe_path_token(value: str) -> str:
        token = str(value or "shared").strip()
        if not token:
            return "shared"
        keep = []
        for char in token:
            if char.isalnum() or char in {"-", "_", "."}:
                keep.append(char)
            else:
                keep.append("_")
        return "".join(keep)

    @staticmethod
    def _ensure_writable_dir(primary: Path, fallback: Path) -> Path:
        for candidate in (primary, fallback):
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                test_file = candidate / ".write_test"
                test_file.write_text("ok", encoding="utf-8")
                test_file.unlink(missing_ok=True)
                return candidate
            except Exception:
                continue
        raise PermissionError(
            f"Unable to create a writable directory at {primary} or fallback {fallback}"
        )
