"""On-device voice models (REDESIGN §18). What a device downloads depends on its hardware tier;
fitness then benchmarks each one like any other engine and keeps what fits. All models come from
the sherpa-onnx releases, pinned by sha256 (GitHub's asset digest), and run on CPU via sherpa-onnx.

Measured on a low-spec laptop (Ryzen 7 4700U, 8 GB, 2026-10-10): fp32 models ran ~4x faster than
int8 (no VNNI), Piper fp32 spoke the 12-word probe in ~230 ms, Kokoro fp32 in ~1.7 s; Moonshine-tiny
transcribed a 2.5 s command in ~120 ms at ~10% WER. Kokoro and Parakeet-0.6B only go to strong PCs.
"""

from __future__ import annotations

import hashlib
import shutil
import tarfile
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Literal

RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
OK = ".ok"  # written last: a folder without it is a half-finished download

Role = Literal["wake", "stt", "tts"]
Kind = Literal["kws", "vits", "kokoro", "moonshine", "nemo_transducer"]


@dataclass(frozen=True)
class Model:
    name: str  # engine name and folder under models/
    role: Role
    kind: Kind  # which sherpa-onnx config builds it
    asset: str  # "<release tag>/<archive>"
    sha256: str
    mb: int
    min_tier: int  # 0 low-spec, 1 mid, 2 high (tier())
    license: str
    sid: int = 0  # speaker, for multi-speaker voices


CATALOG: tuple[Model, ...] = (
    Model(
        "kws-gigaspeech",
        "wake",
        "kws",
        "kws-models/sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01.tar.bz2",
        "f170013b4716e41b62b9bfd809687c207cef798ef9bc6534d524e17af9b6561a",
        18,
        0,
        "Apache-2.0",
    ),
    Model(
        "piper",
        "tts",
        "vits",
        "tts-models/vits-piper-en_US-libritts_r-medium.tar.bz2",
        "10dc268f3e371696d721486123e2705a9fc1faa113491979fde4d88dba1f1b1c",
        82,
        0,
        "MIT (Piper), voice data CC-BY-4.0 (LibriTTS-R)",
    ),
    Model(
        "moonshine-tiny",
        "stt",
        "moonshine",
        "asr-models/sherpa-onnx-moonshine-tiny-en-int8.tar.bz2",
        "d5fe6ec4334fef36255b2a4010412cad4c007e33103fec62fb5d17cad88086f2",
        108,
        0,
        "MIT",
    ),
    Model(
        "kokoro",
        "tts",
        "kokoro",
        "tts-models/kokoro-multi-lang-v1_0.tar.bz2",
        "c5f7e2d2caf082bc1d20fb70334a61d99d20b484500aad32e7cf84c128ea3298",
        350,
        2,
        "Apache-2.0",
        sid=16,  # am_michael
    ),
    Model(
        "parakeet",
        "stt",
        "nemo_transducer",
        "asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8.tar.bz2",
        "157c157bc51155e03e37d2466522a3a737dd9c72bb25f36eb18912964161e1ad",
        482,
        2,
        "CC-BY-4.0",
    ),
)
BY_NAME = {m.name: m for m in CATALOG}


def tier(hw: dict[str, Any]) -> int:
    """0 low-spec, 1 mid, 2 high, from the hardware scan. Decides what's worth downloading and
    the TTS budget; the benchmark decides what's used."""
    ram, cores = hw.get("ram_gb") or 0, hw.get("cores") or 0
    if ram >= 15 and cores >= 8:
        return 2
    if ram >= 10 and cores >= 6:
        return 1
    return 0


def wanted(hw: dict[str, Any]) -> list[Model]:
    t = tier(hw)
    return [m for m in CATALOG if m.min_tier <= t]


@cache
def runtime() -> bool:
    """sherpa-onnx installed (the `local` extra)? Without it no local model is usable."""
    try:
        import sherpa_onnx  # noqa: F401
    except ImportError:
        return False
    return True


def installed(root: Path, name: str) -> Path | None:
    folder = root / name
    return folder if (folder / OK).exists() else None


def one(folder: Path, pattern: str) -> str:
    """The single model file matching `pattern` (archives name them per version)."""
    found = sorted(folder.glob(pattern))
    if not found:
        raise FileNotFoundError(f"{folder.name}: no {pattern}")
    return str(found[0])


Progress = Callable[[int, int], None]  # bytes done, bytes total (0 if unknown)


def fetch(m: Model, root: Path, progress: Progress | None = None) -> Path:
    """Download, verify, and unpack one model (blocking; run it in a thread). Idempotent."""
    if (done := installed(root, m.name)) is not None:
        return done
    root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(root).free < m.mb * 3 * 2**20:  # archive + unpacked + headroom
        raise OSError(f"{m.name}: not enough free disk space")
    part, tmp, dest = root / f"{m.name}.part", root / f"{m.name}.tmp", root / m.name
    digest = hashlib.sha256()
    # ponytail: no resume, a broken download restarts on the next app start
    url = f"{RELEASES}/{m.asset}"
    with urllib.request.urlopen(url, timeout=30) as r, part.open("wb") as f:  # noqa: S310
        total, got = int(r.headers.get("Content-Length") or 0), 0
        while chunk := r.read(1 << 20):
            f.write(chunk)
            digest.update(chunk)
            got += len(chunk)
            if progress is not None:
                progress(got, total)
    if digest.hexdigest() != m.sha256:
        part.unlink()
        raise ValueError(f"{m.name}: checksum mismatch")
    shutil.rmtree(tmp, ignore_errors=True)
    with tarfile.open(part, "r:bz2") as tar:
        tar.extractall(tmp, filter="data")  # no absolute paths, no ../, no device files
    part.unlink()
    top = list(tmp.iterdir())
    inner = top[0] if len(top) == 1 and top[0].is_dir() else tmp
    shutil.rmtree(dest, ignore_errors=True)
    inner.rename(dest)
    shutil.rmtree(tmp, ignore_errors=True)
    (dest / OK).touch()
    return dest
