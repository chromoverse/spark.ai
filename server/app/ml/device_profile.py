from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class DeviceProfile:
    """
    Unified runtime device profile used by:
    - ML model config/device selection
    - Runtime dependency bootstrap
    """

    device: str  # "cuda" | "mps" | "cpu"
    backend: str
    gpu_capable: bool
    torch_available: bool
    cuda_available: bool
    mps_available: bool

    def to_dict(self) -> Dict[str, object]:
        return {
            "device": self.device,
            "backend": self.backend,
            "gpu_capable": self.gpu_capable,
            "torch_available": self.torch_available,
            "cuda_available": self.cuda_available,
            "mps_available": self.mps_available,
        }


def detect_device_profile() -> DeviceProfile:
    """
    Detect the best runtime device and GPU capability signal.

    Notes:
    - `device` is what current runtime can use *now*.
    - `gpu_capable` can still be true when CUDA hardware exists but torch-cuda
      is not currently active in this environment.
    """
    torch_available = False
    cuda_available = False
    mps_available = False

    try:
        import torch  # type: ignore

        torch_available = True
        cuda_available = bool(torch.cuda.is_available())
        mps_available = bool(
            hasattr(torch.backends, "mps") and torch.backends.mps.is_available()  # type: ignore[attr-defined]
        )
    except Exception:
        torch_available = False

    if cuda_available:
        return DeviceProfile(
            device="cuda",
            backend="torch_cuda",
            gpu_capable=True,
            torch_available=torch_available,
            cuda_available=True,
            mps_available=mps_available,
        )

    if mps_available:
        return DeviceProfile(
            device="mps",
            backend="torch_mps",
            gpu_capable=True,
            torch_available=torch_available,
            cuda_available=False,
            mps_available=True,
        )

    if _has_nvidia_gpu():
        # Hardware exists but current torch build/environment may not expose CUDA.
        return DeviceProfile(
            device="cpu",
            backend="nvidia_smi_only",
            gpu_capable=True,
            torch_available=torch_available,
            cuda_available=False,
            mps_available=False,
        )

    return DeviceProfile(
        device="cpu",
        backend="cpu",
        gpu_capable=False,
        torch_available=torch_available,
        cuda_available=False,
        mps_available=False,
    )


def _has_nvidia_gpu() -> bool:
    try:
        result = subprocess.run(
            ["nvidia-smi", "-L"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if result.returncode != 0:
            return False
        return bool((result.stdout or "").strip())
    except Exception:
        return False
