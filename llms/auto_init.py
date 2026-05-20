"""
LLM Auto-Init — One command to detect hardware, download best model, and start inference server.

Usage:
    python -m llms.auto_init

What it does:
    1. Detects GPU (NVIDIA CUDA > AMD Vulkan > CPU)
    2. Picks the best model for your hardware
    3. Downloads model + llama.cpp binary if missing
    4. Starts llama-server
    5. Verifies inference works
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Optional

import requests
from tqdm import tqdm

# ─── Paths ────────────────────────────────────────────────────────────────────

def _get_base_dir() -> Path:
    """Use server's AppData path: AppData/Local/SparkAI/models/llms/"""
    if platform.system() == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif platform.system() == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "SparkAI" / "models" / "llms"


def _get_binaries_dir() -> Path:
    if platform.system() == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif platform.system() == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "SparkAI" / "binaries" / "llama-cpp"


# ─── Hardware Detection ───────────────────────────────────────────────────────

def detect_device() -> str:
    """Detect best available compute device: gpu (CUDA) > vulkan > cpu"""
    # Check NVIDIA
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            gpu_info = r.stdout.strip().splitlines()[0]
            print(f"  NVIDIA GPU: {gpu_info}")
            return "gpu"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Check Vulkan (AMD/Intel iGPU)
    try:
        if platform.system() == "Windows":
            r = subprocess.run(
                ["wmic", "path", "win32_VideoController", "get", "name"],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0:
                lines = [l.strip() for l in r.stdout.splitlines() if l.strip() and "Name" not in l]
                if lines:
                    gpu_name = lines[0]
                    if any(x in gpu_name.lower() for x in ["radeon", "amd", "intel"]):
                        print(f"  Vulkan GPU: {gpu_name}")
                        return "vulkan"
        else:
            r = subprocess.run(["vulkaninfo", "--summary"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and "deviceName" in r.stdout:
                print(f"  Vulkan available")
                return "vulkan"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    print("  No GPU detected, using CPU")
    return "cpu"


def get_ram_gb() -> float:
    """Get total system RAM in GB."""
    try:
        import psutil
        return psutil.virtual_memory().total / (1024**3)
    except ImportError:
        # Fallback for Windows
        if platform.system() == "Windows":
            r = subprocess.run(
                ["wmic", "ComputerSystem", "get", "TotalPhysicalMemory"],
                capture_output=True, text=True,
            )
            for line in r.stdout.splitlines():
                line = line.strip()
                if line.isdigit():
                    return int(line) / (1024**3)
        return 8.0  # assume 8GB


# ─── Model Selection ──────────────────────────────────────────────────────────

# Best models per device type (small enough for real-time, good quality)
MODELS = {
    "gpu": {
        "name": "Gemma 4 E4B (CUDA Q8)",
        "url": "https://huggingface.co/bartowski/google_gemma-4-E4B-it-GGUF/resolve/main/google_gemma-4-E4B-it-Q8_0.gguf",
        "filename": "gemma-4-e4b-q8.gguf",
        "size_gb": 8.03,
        "context": 32768,
        "n_gpu_layers": 99,
    },
    "vulkan": {
        "name": "Gemma 4 E2B (Vulkan Q5_K_M)",
        "url": "https://huggingface.co/bartowski/google_gemma-4-E2B-it-GGUF/resolve/main/google_gemma-4-E2B-it-Q5_K_M.gguf",
        "filename": "gemma-4-e2b-q5km.gguf",
        "size_gb": 3.66,
        "context": 8192,
        "n_gpu_layers": 24,
    },
    "cpu": {
        "name": "Gemma 4 E2B (CPU Q4_K_M)",
        "url": "https://huggingface.co/bartowski/google_gemma-4-E2B-it-GGUF/resolve/main/google_gemma-4-E2B-it-Q4_K_M.gguf",
        "filename": "gemma-4-e2b-q4km.gguf",
        "size_gb": 3.46,
        "context": 4096,
        "n_gpu_layers": 0,
    },
}

# For low-RAM systems (<8GB), use smaller model
MODELS_LOW_RAM = {
    "gpu": MODELS["vulkan"],  # Use smaller model even on NVIDIA if low RAM
    "vulkan": {
        "name": "Gemma 4 E2B (Vulkan Q4_K_M)",
        "url": "https://huggingface.co/bartowski/google_gemma-4-E2B-it-GGUF/resolve/main/google_gemma-4-E2B-it-Q4_K_M.gguf",
        "filename": "gemma-4-e2b-q4km.gguf",
        "size_gb": 3.46,
        "context": 4096,
        "n_gpu_layers": 16,
    },
    "cpu": MODELS["cpu"],
}

# llama.cpp binaries
LLAMA_CPP_VERSION = "b8665"
LLAMA_BINARIES = {
    "Windows": {
        "gpu": f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_CPP_VERSION}/llama-{LLAMA_CPP_VERSION}-bin-win-cuda-12.4-x64.zip",
        "vulkan": f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_CPP_VERSION}/llama-{LLAMA_CPP_VERSION}-bin-win-vulkan-x64.zip",
        "cpu": f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_CPP_VERSION}/llama-{LLAMA_CPP_VERSION}-bin-win-cpu-x64.zip",
    },
    "Linux": {
        "gpu": f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_CPP_VERSION}/llama-{LLAMA_CPP_VERSION}-bin-ubuntu-x64-cuda.tar.gz",
        "vulkan": f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_CPP_VERSION}/llama-{LLAMA_CPP_VERSION}-bin-ubuntu-vulkan-x64.tar.gz",
        "cpu": f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_CPP_VERSION}/llama-{LLAMA_CPP_VERSION}-bin-ubuntu-x64.tar.gz",
    },
    "Darwin": {
        "cpu": f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_CPP_VERSION}/llama-{LLAMA_CPP_VERSION}-bin-macos-arm64.tar.gz",
        "gpu": None,
        "vulkan": None,
    },
}


def pick_model(device: str, ram_gb: float) -> dict:
    """Pick the best model for the hardware."""
    if ram_gb < 8:
        return MODELS_LOW_RAM.get(device, MODELS_LOW_RAM["cpu"])
    return MODELS.get(device, MODELS["cpu"])


# ─── Download ─────────────────────────────────────────────────────────────────

def download_file(url: str, dest: Path, desc: str = "") -> Path:
    """Download with progress bar."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        print(f"  Already exists: {dest.name}")
        return dest

    print(f"  Downloading: {desc or dest.name}")
    r = requests.get(url, stream=True, timeout=30)
    r.raise_for_status()
    total = int(r.headers.get("content-length", 0))

    with open(dest, "wb") as f, tqdm(total=total, unit="B", unit_scale=True, desc=dest.name) as bar:
        for chunk in r.iter_content(chunk_size=1024 * 1024):
            f.write(chunk)
            bar.update(len(chunk))

    return dest


def download_binary(device: str) -> Path:
    """Download llama.cpp binary for the platform/device."""
    system = platform.system()
    url = LLAMA_BINARIES.get(system, {}).get(device)
    if not url:
        # Fallback to CPU
        url = LLAMA_BINARIES[system]["cpu"]

    bin_dir = _get_binaries_dir()
    bin_dir.mkdir(parents=True, exist_ok=True)

    exe_name = "llama-server.exe" if system == "Windows" else "llama-server"
    exe_path = bin_dir / exe_name

    if exe_path.exists():
        print(f"  Binary exists: {exe_path}")
        return exe_path

    archive_name = url.split("/")[-1]
    archive_path = bin_dir / archive_name
    download_file(url, archive_path, f"llama.cpp ({device})")

    # Extract
    print(f"  Extracting {archive_name}...")
    if archive_name.endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(bin_dir)
    else:
        import tarfile
        with tarfile.open(archive_path, "r:gz") as tf:
            tf.extractall(bin_dir)

    # Find the executable
    for p in bin_dir.rglob(exe_name):
        if p != exe_path:
            shutil.copy2(p, exe_path)
            break

    archive_path.unlink(missing_ok=True)

    if not exe_path.exists():
        raise FileNotFoundError(f"Could not find {exe_name} after extraction")

    if system != "Windows":
        exe_path.chmod(0o755)

    return exe_path


# ─── Server Management ────────────────────────────────────────────────────────

def start_server(
    exe_path: Path,
    model_path: Path,
    context: int = 8192,
    n_gpu_layers: int = 0,
    port: int = 9001,
) -> subprocess.Popen:
    """Start llama-server as a background process."""
    cmd = [
        str(exe_path),
        "-m", str(model_path),
        "--host", "127.0.0.1",
        "--port", str(port),
        "-c", str(context),
        "-ngl", str(n_gpu_layers),
        "--threads", str(max(2, os.cpu_count() // 2 if os.cpu_count() else 2)),
    ]

    print(f"  Starting: llama-server on port {port}")
    print(f"  Model: {model_path.name}")
    print(f"  Context: {context}, GPU layers: {n_gpu_layers}")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0,
    )

    # Wait for server to be ready
    print("  Waiting for server...", end="", flush=True)
    for i in range(60):
        time.sleep(1)
        try:
            r = requests.get(f"http://127.0.0.1:{port}/health", timeout=2)
            if r.status_code == 200:
                print(" ready!")
                return proc
        except requests.ConnectionError:
            print(".", end="", flush=True)

    proc.kill()
    raise TimeoutError("Server failed to start within 60s")


def test_inference(port: int = 9741) -> str:
    """Quick test to verify inference works."""
    r = requests.post(
        f"http://127.0.0.1:{port}/completion",
        json={
            "prompt": "<start_of_turn>user\nSay hello in one sentence.<end_of_turn>\n<start_of_turn>model\n",
            "n_predict": 50,
            "temperature": 0.7,
            "stream": False,
            "stop": ["<end_of_turn>", "</s>"],
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("content", "").strip()


# ─── Main ─────────────────────────────────────────────────────────────────────

def auto_init(port: int = 9741) -> dict:
    """Full auto-init: detect → download → start → verify."""
    print("=" * 50)
    print("  SparkAI Local LLM Auto-Init")
    print("=" * 50)

    # 1. Detect hardware
    print("\n[1/5] Detecting hardware...")
    device = detect_device()
    ram_gb = get_ram_gb()
    print(f"  RAM: {ram_gb:.1f} GB")
    print(f"  Device: {device}")

    # 2. Pick model
    print("\n[2/5] Selecting model...")
    model_info = pick_model(device, ram_gb)
    print(f"  Selected: {model_info['name']} ({model_info['size_gb']} GB)")

    # 3. Download model
    print("\n[3/5] Ensuring model is available...")
    models_dir = _get_base_dir()
    model_path = models_dir / model_info["filename"]
    download_file(model_info["url"], model_path, model_info["name"])

    # 4. Download binary
    print("\n[4/5] Ensuring llama-server binary...")
    exe_path = download_binary(device)

    # 5. Start server
    print("\n[5/5] Starting inference server...")
    proc = start_server(
        exe_path=exe_path,
        model_path=model_path,
        context=model_info["context"],
        n_gpu_layers=model_info["n_gpu_layers"],
        port=port,
    )

    # Verify
    print("\n  Testing inference...")
    response = test_inference(port)
    print(f"  Response: {response[:100]}")

    result = {
        "status": "ready",
        "device": device,
        "model": model_info["name"],
        "model_path": str(model_path),
        "port": port,
        "pid": proc.pid,
        "context": model_info["context"],
        "n_gpu_layers": model_info["n_gpu_layers"],
    }

    # Save state
    state_file = _get_base_dir() / "server_state.json"
    state_file.write_text(json.dumps(result, indent=2))

    print("\n" + "=" * 50)
    print("  Local LLM ready!")
    print(f"  Endpoint: http://127.0.0.1:{port}")
    print("=" * 50)

    return result


if __name__ == "__main__":
    auto_init()
