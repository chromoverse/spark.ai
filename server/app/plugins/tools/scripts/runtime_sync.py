from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from uuid import uuid4

from app.config import settings
from app.utils.path_manager import PathManager

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeToolsPaths:
    runtime_root: Path
    runtime_manifest: Path
    runtime_registry: Path
    runtime_index: Path
    runtime_tools: Path
    runtime_automation: Path
    runtime_utils: Path
    runtime_generated: Path
    runtime_meta: Path
    runtime_state: Path

    seed_root: Path
    seed_tools_root: Path
    seed_automation: Path
    seed_utils: Path
    seed_manifest: Path
    seed_registry: Path
    seed_index: Path
    seed_manual: Path
    seed_tester: Path
    seed_requirements: Path


@dataclass
class SyncResult:
    synced: bool
    reason: str
    runtime_version: str
    seed_version: str
    runtime_root: str
    source_used: str
    healthy: bool


class ToolsRuntimeSync:
    """
    Sync runtime tools_plugin assets into AppData/Local/SparkAI/tools_plugin.

    Current phase:
    - Runtime source-of-truth: AppData tools_plugin
    - Bootstrap source: external repo-level tools_plugin seed

    Future source (planned):
    - CDN package download + extract into runtime root
    """

    def __init__(self):
        path_manager = PathManager()
        runtime_root = path_manager.get_tools_plugin_dir()

        seed_root = self._resolve_seed_root()
        seed_tools_root = seed_root / "tools"
        seed_automation = seed_root / "automation"
        seed_utils = seed_root / "utils"
        seed_registry = seed_root / "registry" / "tool_registry.json"
        seed_index = seed_root / "registry" / "tool_index.json"

        self.paths = RuntimeToolsPaths(
            runtime_root=runtime_root,
            runtime_manifest=runtime_root / "manifest.json",
            runtime_registry=runtime_root / "registry" / "tool_registry.json",
            runtime_index=runtime_root / "registry" / "tool_index.json",
            runtime_tools=runtime_root / "tools",
            runtime_automation=runtime_root / "automation",
            runtime_utils=runtime_root / "utils",
            runtime_generated=runtime_root / "generated",
            runtime_meta=runtime_root / "_meta",
            runtime_state=runtime_root / "_meta" / "runtime_state.json",
            seed_root=seed_root,
            seed_tools_root=seed_tools_root,
            seed_automation=seed_automation,
            seed_utils=seed_utils,
            seed_manifest=seed_root / "manifest.json",
            seed_registry=seed_registry,
            seed_index=seed_index,
            seed_manual=seed_root / "manual.md",
            seed_tester=seed_root / "tool_tester.py",
            seed_requirements=seed_root / "requirements.txt",
        )

    def sync(self, force: bool = False, prefer_cdn: bool = False) -> SyncResult:
        """Ensure runtime tools folder is present and version aligned."""
        seed_manifest = self._read_manifest(self.paths.seed_manifest)
        runtime_manifest = self._read_manifest(self.paths.runtime_manifest)

        seed_version = str(seed_manifest.get("version", "0.0.0"))
        runtime_version = str(runtime_manifest.get("version", "missing"))

        runtime_healthy = self._runtime_is_valid()
        if not force and runtime_healthy and runtime_manifest and runtime_version == seed_version:
            self._write_runtime_state(
                runtime_version=runtime_version,
                seed_version=seed_version,
                source_used="runtime",
                sync_status="ok",
                last_error="",
            )
            return SyncResult(
                synced=False,
                reason="runtime tools already up-to-date",
                runtime_version=runtime_version,
                seed_version=seed_version,
                runtime_root=str(self.paths.runtime_root),
                source_used="runtime",
                healthy=True,
            )

        if prefer_cdn and settings.TOOLS_CDN_ENABLED:
            try:
                synced_from_cdn = self.download_tools_from_cdn(
                    manifest_url=settings.TOOLS_CDN_MANIFEST_URL,
                    package_url=settings.TOOLS_CDN_PACKAGE_URL,
                )
                if synced_from_cdn:
                    runtime_manifest = self._read_manifest(self.paths.runtime_manifest)
                    runtime_version = str(runtime_manifest.get("version", "unknown"))
                    self._write_runtime_state(
                        runtime_version=runtime_version,
                        seed_version=seed_version,
                        source_used="cdn",
                        sync_status="ok",
                        last_error="",
                    )
                    return SyncResult(
                        synced=True,
                        reason="runtime tools synced from cdn",
                        runtime_version=runtime_version,
                        seed_version=seed_version,
                        runtime_root=str(self.paths.runtime_root),
                        source_used="cdn",
                        healthy=self._runtime_is_valid(),
                    )
            except Exception as exc:
                logger.warning("CDN sync failed, falling back to seed copy: %s", exc)

        try:
            self._sync_from_seed()
        except Exception as exc:
            logger.error("Seed sync failed: %s", exc)
            healthy_after_error = self._runtime_is_valid()
            self._write_runtime_state(
                runtime_version=runtime_version,
                seed_version=seed_version,
                source_used="runtime",
                sync_status="failed",
                last_error=str(exc),
            )
            if healthy_after_error:
                return SyncResult(
                    synced=False,
                    reason="seed sync failed; using existing runtime",
                    runtime_version=runtime_version,
                    seed_version=seed_version,
                    runtime_root=str(self.paths.runtime_root),
                    source_used="runtime",
                    healthy=True,
                )
            raise RuntimeError(
                "Runtime tools bootstrap failed and no valid runtime exists."
            ) from exc

        self._write_runtime_state(
            runtime_version=seed_version,
            seed_version=seed_version,
            source_used="seed_copy",
            sync_status="ok",
            last_error="",
        )
        return SyncResult(
            synced=True,
            reason="runtime tools synced from seed",
            runtime_version=seed_version,
            seed_version=seed_version,
            runtime_root=str(self.paths.runtime_root),
            source_used="seed_copy",
            healthy=self._runtime_is_valid(),
        )

    def download_tools_from_cdn(self, manifest_url: str, package_url: str) -> bool:
        """
        Placeholder CDN path.

        Planned flow:
        1. Download manifest from CDN.
        2. Compare versions.
        3. Download zip from CDN URL.
        2. Extract zip into runtime root.
        3. Validate manifest and registry files.

        Currently disabled intentionally until CDN is finalized.
        """
        if not manifest_url or not package_url:
            raise RuntimeError("CDN enabled but manifest/package URL is missing.")
        raise NotImplementedError("CDN runtime sync path is scaffolded but not active.")

    def _sync_from_seed(self) -> None:
        if not self.paths.seed_root.exists():
            raise FileNotFoundError(f"External tools_plugin seed root not found: {self.paths.seed_root}")
        if not self.paths.seed_tools_root.exists():
            raise FileNotFoundError(f"Seed tools root not found: {self.paths.seed_tools_root}")
        if not self.paths.seed_automation.exists():
            raise FileNotFoundError(f"Seed automation root not found: {self.paths.seed_automation}")
        if not self.paths.seed_utils.exists():
            raise FileNotFoundError(f"Seed utils root not found: {self.paths.seed_utils}")
        if not self.paths.seed_registry.exists():
            raise FileNotFoundError(f"Seed registry not found: {self.paths.seed_registry}")
        if not self.paths.seed_index.exists():
            raise FileNotFoundError(f"Seed index not found: {self.paths.seed_index}")
        if not self.paths.seed_manifest.exists():
            raise FileNotFoundError(f"Seed manifest not found: {self.paths.seed_manifest}")

        runtime_parent = self.paths.runtime_root.parent
        runtime_parent.mkdir(parents=True, exist_ok=True)
        temp_root = runtime_parent / f"{self.paths.runtime_root.name}.tmp-{uuid4().hex[:8]}"
        backup_root = runtime_parent / f"{self.paths.runtime_root.name}.bak"

        if temp_root.exists():
            shutil.rmtree(temp_root, ignore_errors=True)
        if backup_root.exists():
            shutil.rmtree(backup_root, ignore_errors=True)

        ignore_patterns = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
        temp_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.paths.seed_tools_root, temp_root / "tools", ignore=ignore_patterns)
        shutil.copytree(self.paths.seed_automation, temp_root / "automation", ignore=ignore_patterns)
        shutil.copytree(self.paths.seed_utils, temp_root / "utils", ignore=ignore_patterns)
        shutil.copytree(self.paths.seed_registry.parent, temp_root / "registry", ignore=ignore_patterns)

        if self.paths.seed_manual.exists():
            shutil.copy2(self.paths.seed_manual, temp_root / "manual.md")

        if self.paths.seed_tester.exists():
            shutil.copy2(self.paths.seed_tester, temp_root / "tool_tester.py")
        if self.paths.seed_requirements.exists():
            shutil.copy2(self.paths.seed_requirements, temp_root / "requirements.txt")

        shutil.copy2(self.paths.seed_manifest, temp_root / "manifest.json")
        (temp_root / "__init__.py").write_text("", encoding="utf-8")
        (temp_root / "generated").mkdir(parents=True, exist_ok=True)
        (temp_root / "_meta").mkdir(parents=True, exist_ok=True)
        self._ensure_package_marker(temp_root / "tools")
        self._ensure_package_marker(temp_root / "automation")
        self._ensure_package_marker(temp_root / "utils")
        self._ensure_package_marker(temp_root / "registry")

        if self.paths.runtime_root.exists():
            try:
                self.paths.runtime_root.rename(backup_root)
            except PermissionError:
                logger.warning(
                    "Runtime root is locked; applying in-place sync instead of atomic swap: %s",
                    self.paths.runtime_root,
                )
                self._sync_in_place(temp_root, self.paths.runtime_root)
                if temp_root.exists():
                    shutil.rmtree(temp_root, ignore_errors=True)
                if backup_root.exists():
                    shutil.rmtree(backup_root, ignore_errors=True)
                logger.info("Runtime tools_plugin synced in-place to %s", self.paths.runtime_root)
                return
        try:
            temp_root.rename(self.paths.runtime_root)
        except Exception:
            if self.paths.runtime_root.exists():
                shutil.rmtree(self.paths.runtime_root, ignore_errors=True)
            if backup_root.exists():
                backup_root.rename(self.paths.runtime_root)
            raise
        finally:
            if temp_root.exists():
                shutil.rmtree(temp_root, ignore_errors=True)

        if backup_root.exists():
            shutil.rmtree(backup_root, ignore_errors=True)

        logger.info("Runtime tools_plugin synced to %s", self.paths.runtime_root)

    @staticmethod
    def _sync_in_place(source_root: Path, target_root: Path) -> None:
        target_root.mkdir(parents=True, exist_ok=True)
        for item in source_root.iterdir():
            destination = target_root / item.name
            if item.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                shutil.copytree(item, destination, dirs_exist_ok=True)
            else:
                shutil.copy2(item, destination)

    @staticmethod
    def _resolve_seed_root() -> Path:
        configured = os.environ.get("SPARK_TOOLS_PLUGIN_SEED_DIR", "").strip()
        if configured:
            return Path(configured).expanduser().resolve()
        # server/app/plugins/tools/scripts/runtime_sync.py -> repo root at parents[5]
        repo_root = Path(__file__).resolve().parents[5]
        return (repo_root / "tools_plugin").resolve()

    def _runtime_is_valid(self) -> bool:
        required_paths = (
            self.paths.runtime_root,
            self.paths.runtime_manifest,
            self.paths.runtime_registry,
            self.paths.runtime_index,
            self.paths.runtime_tools,
            self.paths.runtime_automation,
            self.paths.runtime_utils,
            self.paths.runtime_root / "requirements.txt",
        )
        return all(path.exists() for path in required_paths)

    def _write_runtime_state(
        self,
        runtime_version: str,
        seed_version: str,
        source_used: str,
        sync_status: str,
        last_error: str,
    ) -> None:
        self.paths.runtime_meta.mkdir(parents=True, exist_ok=True)
        payload = {
            "runtime_version": runtime_version,
            "seed_version": seed_version,
            "last_sync_at": datetime.now(timezone.utc).isoformat(),
            "source_used": source_used,
            "sync_status": sync_status,
            "last_error": last_error,
            "runtime_root": str(self.paths.runtime_root),
            "healthy": self._runtime_is_valid(),
        }
        self.paths.runtime_state.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _ensure_package_marker(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        marker = path / "__init__.py"
        if not marker.exists():
            marker.write_text("", encoding="utf-8")

    @staticmethod
    def _read_manifest(path: Path) -> dict:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)


_runtime_sync: Optional[ToolsRuntimeSync] = None


def get_tools_runtime_sync() -> ToolsRuntimeSync:
    global _runtime_sync
    if _runtime_sync is None:
        _runtime_sync = ToolsRuntimeSync()
    return _runtime_sync


def get_runtime_tools_paths() -> RuntimeToolsPaths:
    return get_tools_runtime_sync().paths
