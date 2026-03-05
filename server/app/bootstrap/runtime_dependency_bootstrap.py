from __future__ import annotations

import asyncio
import logging
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from importlib import metadata
import re
from typing import List

from app.config import settings
from app.ml.device_profile import DeviceProfile, detect_device_profile

logger = logging.getLogger(__name__)


@dataclass
class RuntimeDependencyReport:
    profile: DeviceProfile
    required: List[str]
    installed: List[str]
    missing: List[str]
    failed: List[str]
    auto_install_enabled: bool
    elapsed_ms: float

    @property
    def ok(self) -> bool:
        return len(self.failed) == 0

    def to_dict(self) -> dict:
        return {
            "profile": self.profile.to_dict(),
            "required": self.required,
            "installed": self.installed,
            "missing": self.missing,
            "failed": self.failed,
            "auto_install_enabled": self.auto_install_enabled,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "ok": self.ok,
        }


_last_report: RuntimeDependencyReport | None = None
_REQ_NAME_PATTERN = re.compile(r"^\s*([A-Za-z0-9_.-]+)")

try:
    from packaging.requirements import Requirement as _PackagingRequirement
except Exception:  # pragma: no cover - fallback path if packaging is unavailable
    _PackagingRequirement = None  # type: ignore[assignment]


def get_last_runtime_dependency_report() -> RuntimeDependencyReport | None:
    return _last_report


async def ensure_runtime_dependencies() -> RuntimeDependencyReport:
    """
    Ensure required runtime packages are present for the detected device profile.
    Installs missing packages in the current Python environment if enabled.
    """
    global _last_report

    started = time.perf_counter()
    profile = detect_device_profile()
    required = _build_required_packages(profile)
    missing = [pkg for pkg in required if not _is_package_installed(pkg)]
    installed: List[str] = []
    failed: List[str] = []

    auto_install_enabled = bool(getattr(settings, "RUNTIME_AUTO_INSTALL_ENABLED", True))
    timeout_sec = max(60, int(getattr(settings, "RUNTIME_REQUIREMENTS_TIMEOUT_SEC", 900)))

    if missing and auto_install_enabled:
        logger.info(
            "📦 Runtime dependency bootstrap: missing=%s profile=%s, auto-installing...",
            missing,
            profile.to_dict(),
        )
        for pkg in missing:
            ok = await _pip_install(pkg, timeout_sec=timeout_sec)
            if ok:
                installed.append(pkg)
            else:
                failed.append(pkg)
    elif missing:
        logger.warning(
            "⚠️ Runtime dependency bootstrap: missing packages detected but auto-install disabled: %s",
            missing,
        )
    else:
        logger.info("✅ Runtime dependency bootstrap: all required packages already installed.")

    elapsed_ms = (time.perf_counter() - started) * 1000
    report = RuntimeDependencyReport(
        profile=profile,
        required=required,
        installed=installed,
        missing=missing,
        failed=failed,
        auto_install_enabled=auto_install_enabled,
        elapsed_ms=elapsed_ms,
    )
    _last_report = report

    if report.ok:
        logger.info(
            "✅ Runtime dependency bootstrap complete (device=%s backend=%s gpu_capable=%s elapsed=%.0fms)",
            profile.device,
            profile.backend,
            profile.gpu_capable,
            elapsed_ms,
        )
    else:
        logger.error(
            "❌ Runtime dependency bootstrap failed for packages=%s (elapsed=%.0fms)",
            report.failed,
            elapsed_ms,
        )

    return report


def _build_required_packages(profile: DeviceProfile) -> List[str]:
    core = _parse_csv(getattr(settings, "RUNTIME_REQUIREMENTS_CORE", ""))
    cpu_extra = _parse_csv(getattr(settings, "RUNTIME_REQUIREMENTS_CPU_EXTRA", ""))
    cuda_extra = _parse_csv(getattr(settings, "RUNTIME_REQUIREMENTS_CUDA_EXTRA", ""))
    mps_extra = _parse_csv(getattr(settings, "RUNTIME_REQUIREMENTS_MPS_EXTRA", ""))
    legacy_gpu_extra = _parse_csv(getattr(settings, "RUNTIME_REQUIREMENTS_GPU_EXTRA", ""))

    desired = list(core)
    if profile.device == "mps":
        desired.extend(mps_extra or cpu_extra)
    elif profile.device == "cuda" or profile.backend == "nvidia_smi_only":
        desired.extend(cuda_extra)
        desired.extend(legacy_gpu_extra)
    else:
        desired.extend(cpu_extra)

    deduped: List[str] = []
    seen = set()
    for pkg in desired:
        name = pkg.strip()
        if not _requirement_applies(name):
            continue
        if not name or name in seen:
            continue
        deduped.append(name)
        seen.add(name)
    return deduped


def _parse_csv(raw: str) -> List[str]:
    return [item.strip() for item in (raw or "").split(",") if item.strip()]


def _requirement_applies(requirement_spec: str) -> bool:
    if not requirement_spec:
        return False
    if _PackagingRequirement is None:
        return True
    try:
        req = _PackagingRequirement(requirement_spec)
        if req.marker is None:
            return True
        return bool(req.marker.evaluate())
    except Exception:
        return True


def _extract_requirement_name(requirement_spec: str) -> str:
    spec = (requirement_spec or "").strip()
    if not spec:
        return ""
    if _PackagingRequirement is not None:
        try:
            return str(_PackagingRequirement(spec).name)
        except Exception:
            pass
    match = _REQ_NAME_PATTERN.match(spec)
    return match.group(1) if match else spec


def _is_package_installed(requirement_spec: str) -> bool:
    try:
        if not _requirement_applies(requirement_spec):
            return True

        package_name = _extract_requirement_name(requirement_spec)
        if not package_name:
            return True

        installed_version = metadata.version(package_name)

        if _PackagingRequirement is not None:
            try:
                req = _PackagingRequirement(requirement_spec)
                if req.specifier and not req.specifier.contains(installed_version, prereleases=True):
                    return False
            except Exception:
                # Fall through to best-effort installed check.
                pass
        return True
    except metadata.PackageNotFoundError:
        return False
    except Exception:
        return False


async def _pip_install(package_name: str, timeout_sec: int) -> bool:
    pip_args = _parse_pip_args(getattr(settings, "RUNTIME_PIP_INSTALL_ARGS", ""))
    cmd = [sys.executable, "-m", "pip", "install", package_name, *pip_args]
    logger.info("🔧 Installing missing runtime package: %s", package_name)

    def _run() -> bool:
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                check=False,
            )
            if proc.returncode == 0:
                logger.info("✅ Installed %s", package_name)
                return True
            logger.error(
                "❌ Failed installing %s (code=%s): %s",
                package_name,
                proc.returncode,
                (proc.stderr or proc.stdout or "").strip()[:600],
            )
            return False
        except Exception as exc:
            logger.error("❌ Exception installing %s: %s", package_name, exc)
            return False

    return await asyncio.to_thread(_run)


def _parse_pip_args(raw: str) -> List[str]:
    value = (raw or "").strip()
    if not value:
        return []
    try:
        return [arg for arg in shlex.split(value, posix=False) if arg]
    except Exception:
        return []
