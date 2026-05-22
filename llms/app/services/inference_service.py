"""
Inference Service — LLM inference via llama-server subprocess.

Optimized for real-time voice assistant usage:
    - Hardware-aware model/backend selection (VRAM, RAM, GPU)
    - Optimized llama-server flags (flash-attn, cont-batching, mlock)
    - Native chat templates via --jinja
    - Generation cancellation for interruption support
    - Parallel slots for concurrent requests
"""

import os
import re
import shutil
import subprocess
import zipfile
import time
import signal
import json
import platform
from pathlib import Path
from typing import Optional, List, Dict, Any
from threading import Lock

import requests
from tqdm import tqdm

from app.services.path_manager import PathManager, get_path_manager
from app.services.model_manager import ModelManager, get_model_manager
from app.core.config import settings


def detect_hardware() -> Dict[str, Any]:
    """Detect GPU, VRAM, RAM, and CPU capabilities for intelligent model selection."""
    hw = {
        "ram_total_gb": 8.0,
        "ram_available_gb": 4.0,
        "gpu_vendor": None,
        "gpu_name": None,
        "vram_mb": 0,
        "cuda": False,
        "cuda_version": None,
        "vulkan": False,
        "cpu_cores": os.cpu_count() or 4,
        "device": "cpu",
    }

    # RAM detection
    try:
        import psutil
        vm = psutil.virtual_memory()
        hw["ram_total_gb"] = round(vm.total / 1024**3, 1)
        hw["ram_available_gb"] = round(vm.available / 1024**3, 1)
    except ImportError:
        if platform.system() == "Windows":
            try:
                r = subprocess.run(
                    ["wmic", "ComputerSystem", "get", "TotalPhysicalMemory"],
                    capture_output=True, text=True, timeout=5,
                )
                for line in r.stdout.splitlines():
                    line = line.strip()
                    if line.isdigit():
                        hw["ram_total_gb"] = round(int(line) / 1024**3, 1)
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

    # NVIDIA GPU + VRAM
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            parts = [p.strip() for p in r.stdout.strip().splitlines()[0].split(",")]
            hw["gpu_vendor"] = "nvidia"
            hw["gpu_name"] = parts[0]
            hw["vram_mb"] = int(parts[1])
            hw["cuda"] = True
            hw["device"] = "gpu"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # CUDA version
    if hw["cuda"]:
        try:
            r = subprocess.run(["nvcc", "--version"], capture_output=True, text=True, timeout=3)
            m = re.search(r"release (\d+\.\d+)", r.stdout)
            if m:
                hw["cuda_version"] = m.group(1)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    # Apple Silicon (macOS Metal) — llama.cpp uses Metal automatically on ARM Macs
    if hw["device"] == "cpu" and platform.system() == "Darwin":
        try:
            r = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True, timeout=3,
            )
            is_apple_silicon = "apple" in r.stdout.lower() if r.returncode == 0 else False
            if not is_apple_silicon:
                r = subprocess.run(["uname", "-m"], capture_output=True, text=True, timeout=3)
                is_apple_silicon = "arm64" in r.stdout.lower()

            if is_apple_silicon:
                hw["gpu_vendor"] = "apple"
                hw["gpu_name"] = "Apple Silicon (Metal)"
                hw["device"] = "metal"
                # Unified memory — all RAM is available as VRAM
                hw["vram_mb"] = int(hw["ram_total_gb"] * 1024)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    # AMD/Intel Vulkan (only if no NVIDIA and not Apple Silicon)
    if hw["device"] == "cpu":
        try:
            if platform.system() == "Windows":
                r = subprocess.run(
                    ["wmic", "path", "win32_VideoController", "get", "name"],
                    capture_output=True, text=True, timeout=5,
                )
                if r.returncode == 0:
                    lines = [l.strip() for l in r.stdout.splitlines()
                             if l.strip() and "Name" not in l]
                    if lines:
                        gpu_name = lines[0]
                        if any(x in gpu_name.lower() for x in ["radeon", "amd", "intel"]):
                            hw["gpu_vendor"] = "amd" if "amd" in gpu_name.lower() or "radeon" in gpu_name.lower() else "intel"
                            hw["gpu_name"] = gpu_name
                            hw["vulkan"] = True
                            hw["device"] = "vulkan"
            else:
                r = subprocess.run(
                    ["vulkaninfo", "--summary"],
                    capture_output=True, text=True, timeout=5,
                )
                if r.returncode == 0 and "deviceName" in r.stdout:
                    hw["vulkan"] = True
                    hw["device"] = "vulkan"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    return hw


def pick_optimal_config(hw: Dict[str, Any]) -> Dict[str, Any]:
    """Pick context size, GPU layers, thread count, and memory flags based on hardware.

    Key principle for low-RAM systems (<10GB):
      - Keep model small (Q4_K_M chosen by model_manager)
      - Keep context small (2048) so KV cache stays tiny
      - Don't mlock (let OS page out cold model pages rather than starving other apps)
      - Use parallel=1 (each slot allocates its own KV cache)
      - Only offload a few layers to iGPU (512MB-1GB VRAM can't hold much)
    """
    device = hw["device"]
    ram = hw["ram_total_gb"]
    vram = hw["vram_mb"]
    cores = hw["cpu_cores"]
    low_ram = ram < 10

    threads = max(2, cores // 2)

    # Apple Silicon — unified memory, Metal backend, always fast
    if device == "metal":
        if ram >= 32:
            return {"context": 16384, "n_gpu_layers": 99, "threads": threads,
                    "parallel": 2, "mlock": True}
        elif ram >= 16:
            return {"context": 8192, "n_gpu_layers": 99, "threads": threads,
                    "parallel": 2, "mlock": True}
        else:
            return {"context": 4096, "n_gpu_layers": 99, "threads": threads,
                    "parallel": 1, "mlock": not low_ram}

    if device == "gpu":
        if vram >= 12000:
            return {"context": 16384, "n_gpu_layers": 99, "threads": threads,
                    "parallel": 2, "mlock": True}
        elif vram >= 6000:
            return {"context": 8192, "n_gpu_layers": 99, "threads": threads,
                    "parallel": 2, "mlock": True}
        elif vram >= 4000:
            return {"context": 4096, "n_gpu_layers": 99, "threads": threads,
                    "parallel": 1 if low_ram else 2, "mlock": not low_ram}
        else:
            return {"context": 4096, "n_gpu_layers": 24, "threads": threads,
                    "parallel": 1, "mlock": not low_ram}

    if device == "vulkan":
        if vram >= 4000 and ram >= 16:
            return {"context": 8192, "n_gpu_layers": 99, "threads": threads,
                    "parallel": 2, "mlock": True}
        elif vram >= 2000 and ram >= 12:
            return {"context": 4096, "n_gpu_layers": 24, "threads": threads,
                    "parallel": 2, "mlock": True}
        else:
            # iGPU / low VRAM (<2GB) / low RAM — mostly CPU-bound
            ngl = 0 if vram < 1024 else 8
            return {"context": 2048, "n_gpu_layers": ngl, "threads": threads,
                    "parallel": 1, "mlock": False}

    # CPU
    if ram >= 16:
        return {"context": 8192, "n_gpu_layers": 0, "threads": threads,
                "parallel": 2, "mlock": True}
    elif ram >= 10:
        return {"context": 4096, "n_gpu_layers": 0, "threads": threads,
                "parallel": 1, "mlock": True}
    return {"context": 2048, "n_gpu_layers": 0, "threads": threads,
            "parallel": 1, "mlock": False}


class InferenceService:
    """
    LLM Inference Service using llama-server.
    Hardware-aware, optimized for real-time voice assistant usage.
    """

    LLAMA_CPP_VERSION = "b8665"
    LLAMA_CPP_RELEASES = {
        "Windows": {
            "cpu": {
                "url": f"https://github.com/ggml-org/llama.cpp/releases/download/b8665/llama-b8665-bin-win-cpu-x64.zip",
                "executable": "llama-server.exe",
                "size_mb": 35
            },
            "gpu": {
                "url": f"https://github.com/ggml-org/llama.cpp/releases/download/b8665/llama-b8665-bin-win-cuda-12.4-x64.zip",
                "executable": "llama-server.exe",
                "size_mb": 450
            },
            "vulkan": {
                "url": f"https://github.com/ggml-org/llama.cpp/releases/download/b8665/llama-b8665-bin-win-vulkan-x64.zip",
                "executable": "llama-server.exe",
                "size_mb": 40
            }
        },
        "Darwin": {
            "cpu": {
                "url": f"https://github.com/ggml-org/llama.cpp/releases/download/b8665/llama-b8665-bin-macos-arm64.tar.gz",
                "executable": "llama-server",
                "size_mb": 15
            },
            "gpu": None,
        },
        "Linux": {
            "cpu": {
                "url": f"https://github.com/ggml-org/llama.cpp/releases/download/b8665/llama-b8665-bin-ubuntu-x64.tar.gz",
                "executable": "llama-server",
                "size_mb": 35
            },
            "gpu": {
                "url": f"https://github.com/ggml-org/llama.cpp/releases/download/b8665/llama-b8665-bin-ubuntu-x64-cuda.tar.gz",
                "executable": "llama-server",
                "size_mb": 400
            },
            "vulkan": {
                "url": f"https://github.com/ggml-org/llama.cpp/releases/download/b8665/llama-b8665-bin-ubuntu-vulkan-x64.tar.gz",
                "executable": "llama-server",
                "size_mb": 35
            }
        }
    }

    SERVER_HOST = "127.0.0.1"
    SERVER_PORT = 8080

    def __init__(
        self,
        path_manager: Optional[PathManager] = None,
        model_manager: Optional[ModelManager] = None
    ):
        self.path_manager = path_manager or get_path_manager()
        self.model_manager = model_manager or get_model_manager()

        self.model_path: Optional[Path] = None
        self.server_path: Optional[Path] = None
        self.server_process: Optional[subprocess.Popen] = None

        self.system = self.path_manager.system
        self.hardware = detect_hardware()
        self.device_type = self.hardware["device"]
        self.optimal_config = pick_optimal_config(self.hardware)
        self._is_ready = False
        self._lock = Lock()

        print(f"🖥️  Hardware: {self.hardware['gpu_name'] or 'CPU'} | "
              f"RAM: {self.hardware['ram_total_gb']}GB | "
              f"VRAM: {self.hardware['vram_mb']}MB | "
              f"Device: {self.device_type.upper()}")

    def _get_release_info(self) -> Dict[str, Any]:
        """Get llama.cpp release info for current OS and device.

        Key: if n_gpu_layers=0, use the CPU binary even on Vulkan/Metal systems.
        The CPU binary has AVX2/SSE optimizations that are faster than the
        Vulkan binary doing CPU-only inference.
        """
        os_releases = self.LLAMA_CPP_RELEASES.get(self.system, {})
        device_key = self.device_type

        # Metal uses macOS CPU binary (includes Metal)
        if device_key == "metal":
            device_key = "cpu"
        # If we're not offloading any layers, use the CPU binary for better perf
        elif self.optimal_config.get("n_gpu_layers", 0) == 0:
            device_key = "cpu"

        release = os_releases.get(device_key)
        if release is None:
            release = os_releases.get("cpu")
        if release is None:
            raise NotImplementedError(
                f"No llama.cpp release for {self.system}/{self.device_type}"
            )
        return release

    def _get_release_tag(self, url: str) -> str:
        """Extract the release tag from a GitHub release URL."""
        match = re.search(r"/download/([^/]+)/", url)
        if match:
            return match.group(1)
        return self.LLAMA_CPP_VERSION

    def _get_release_asset_name(self, url: str) -> str:
        """Get the archive filename from the download URL."""
        return url.rstrip("/").split("/")[-1]

    def _get_release_install_dir(self, release_info: Dict[str, Any]) -> Path:
        """Return the versioned install directory for the current binary."""
        asset_name = self._get_release_asset_name(release_info["url"])
        if asset_name.endswith(".tar.gz"):
            dir_name = asset_name[:-7]
        elif asset_name.endswith(".zip"):
            dir_name = asset_name[:-4]
        else:
            dir_name = Path(asset_name).stem
        return self.path_manager.get_binaries_dir() / dir_name

    def _find_executable(self, root_dir: Path, exe_name: str) -> Optional[Path]:
        """Search for an executable inside a directory tree."""
        if not root_dir.exists():
            return None

        if root_dir.is_file():
            return root_dir if root_dir.name == exe_name else None

        direct_path = root_dir / exe_name
        if direct_path.exists():
            return direct_path

        for root, _, files in os.walk(root_dir):
            if exe_name in files:
                return Path(root) / exe_name
        return None

    def _needs_binary_refresh(self, binary_path: Path, release_info: Dict[str, Any]) -> bool:
        """Refresh non-versioned binaries so new model support can be picked up."""
        expected_dir = self._get_release_install_dir(release_info)
        expected_dir = expected_dir.resolve()
        binary_path = binary_path.resolve()
        return expected_dir != binary_path and expected_dir not in binary_path.parents

    def _download_llama_binary(self) -> Path:
        """Download and extract llama.cpp binary."""
        release_info = self._get_release_info()
        binaries_dir = self.path_manager.get_binaries_dir()
        
        print(f"\n⚠️  llama-server not found. Downloading llama.cpp binary...")
        print(f"📦 Size: ~{release_info['size_mb']} MB")
        print(f"🎯 Platform: {self.system} ({self.device_type.upper()})")
        
        url = release_info['url'].strip()
        is_zip = url.endswith('.zip')
        ext = '.zip' if is_zip else '.tar.gz'
        release_tag = self._get_release_tag(url)
        asset_name = self._get_release_asset_name(url)
        install_dir = self._get_release_install_dir(release_info)
        archive_path = binaries_dir / asset_name
        
        print(f"⬇️  Downloading from GitHub releases...")
        response = requests.get(url, stream=True)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        with open(archive_path, 'wb') as f, tqdm(
            desc="llama.cpp",
            total=total_size,
            unit='iB',
            unit_scale=True,
            unit_divisor=1024,
        ) as progress_bar:
            for chunk in response.iter_content(chunk_size=8192):
                size = f.write(chunk)
                progress_bar.update(size)
        
        print(f"📦 Extracting...")
        if install_dir.exists():
            shutil.rmtree(install_dir)
        install_dir.mkdir(parents=True, exist_ok=True)

        if is_zip:
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                zip_ref.extractall(install_dir)
        else:
            import tarfile
            with tarfile.open(archive_path, 'r:gz') as tar_ref:
                tar_ref.extractall(install_dir)
        
        exe_name = release_info['executable']
        extracted_exe = self._find_executable(install_dir, exe_name)
        
        archive_path.unlink()
        
        if not extracted_exe or not extracted_exe.exists():
            raise FileNotFoundError(f"Could not find {exe_name} after extraction")
        
        print(f"🧩 Installed llama.cpp release: {release_tag}")
        print(f"✅ Downloaded: {extracted_exe}")
        return extracted_exe

    def _find_llama_binary(self) -> Optional[Path]:
        """Search for llama-server in known locations."""
        release_info = self._get_release_info()
        exe_name = release_info['executable']
        
        bundle_dir = self.path_manager.get_bundle_dir()
        binaries_dir = self.path_manager.get_binaries_dir()
        install_dir = self._get_release_install_dir(release_info)

        expected_binary = self._find_executable(install_dir, exe_name)
        if expected_binary:
            return expected_binary
        
        search_locations = [
            bundle_dir / "tools" / exe_name,
            bundle_dir / exe_name,
            binaries_dir / exe_name,
        ]
        
        for root, _, files in os.walk(binaries_dir):
            if exe_name in files:
                return Path(root) / exe_name

        for path in search_locations:
            if path.exists():
                return path
        return None

    def setup(self, auto_download_binary: bool = True) -> None:
        """Setup model and start background server."""
        with self._lock:
            if self._is_ready:
                print("✅ Inference service already initialized")
                return
            
            print("\n" + "=" * 50)
            print("🚀 Initializing Inference Service (Server Mode)")
            print("=" * 50)
            
            self.model_path = self.model_manager.get_model_path(
                settings.model_name,
                auto_download=settings.auto_download_model
            )
            
            self.server_path = self._find_llama_binary()
            if self.server_path and auto_download_binary and self._needs_binary_refresh(self.server_path, self._get_release_info()):
                print("♻️  Existing llama-server binary is stale for the configured release. Refreshing...")
                self.server_path = None

            if not self.server_path and auto_download_binary:
                try:
                    self.server_path = self._download_llama_binary()
                except Exception as e:
                    print(f"❌ Binary download failed: {e}")
                    raise
            
            if not self.server_path:
                raise FileNotFoundError("llama-server not found.")
            
            self._start_server()
            self._is_ready = True
            print("\n🎉 Inference service ready!")

    def _wait_for_server_ready(self, timeout_seconds: int = 120) -> None:
        """Wait for llama-server health endpoint to become ready."""
        print("⏳ Waiting for server...", end="", flush=True)
        for i in range(timeout_seconds):
            if self.server_process is None:
                raise RuntimeError("llama-server process was not started")
            if self.server_process.poll() is not None:
                stderr = ""
                if self.server_process.stderr:
                    try:
                        stderr = self.server_process.stderr.read().decode("utf-8", errors="replace")[-500:]
                    except Exception:
                        pass
                raise RuntimeError(
                    f"llama-server died with code {self.server_process.returncode}. "
                    f"Stderr: {stderr}"
                )
            try:
                r = requests.get(
                    f"http://{self.SERVER_HOST}:{self.SERVER_PORT}/health", timeout=1
                )
                if r.status_code == 200:
                    print(" ready!")
                    return
            except requests.RequestException:
                pass
            time.sleep(1)
            if i % 10 == 0:
                print(".", end="", flush=True)

        raise RuntimeError(f"llama-server failed to start within {timeout_seconds}s")

    def _build_server_cmd(self, cfg: Dict[str, Any]) -> List[str]:
        """Build the llama-server command with hardware-appropriate flags."""
        cmd = [
            str(self.server_path),
            "-m", str(self.model_path),
            "--host", self.SERVER_HOST,
            "--port", str(self.SERVER_PORT),
            "-c", str(cfg["context"]),
            "-ngl", str(cfg["n_gpu_layers"]),
            "--threads", str(cfg["threads"]),
            # Always-on optimizations
            "--flash-attn", "auto",
            "--cont-batching",
            "--parallel", str(cfg.get("parallel", 1)),
            # KV cache compression (saves RAM/VRAM significantly)
            "--cache-type-k", "q8_0",
            "--cache-type-v", "q4_0",
            # Native chat template
            "--jinja",
        ]
        if cfg.get("mlock"):
            cmd.append("--mlock")
        return cmd

    def _start_server(self):
        """Start llama-server with hardware-optimized configuration."""
        cfg = self.optimal_config

        opts = ["flash-attn", "cont-batching", f"parallel={cfg.get('parallel', 1)}", "KV q8/q4"]
        if cfg.get("mlock"):
            opts.append("mlock")
        else:
            opts.append("no-mlock (RAM saver)")

        print(f"⏳ Starting llama-server...")
        print(f"🔧 Config: ctx={cfg['context']} | ngl={cfg['n_gpu_layers']} | threads={cfg['threads']} | device={self.device_type.upper()}")
        print(f"⚡ Optimizations: {', '.join(opts)}")

        cmd = self._build_server_cmd(cfg)

        self.server_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )

        try:
            self._wait_for_server_ready(timeout_seconds=120)
        except RuntimeError as primary_err:
            self.shutdown()
            print(f"⚠️  Primary config failed: {primary_err}")
            print("⚠️  Trying safe fallback (no flash-attn, no mlock, ngl=0)...")
            fallback_cmd = [
                str(self.server_path),
                "-m", str(self.model_path),
                "--host", self.SERVER_HOST,
                "--port", str(self.SERVER_PORT),
                "-c", str(min(cfg["context"], 2048)),
                "-ngl", "0",
                "--threads", str(cfg["threads"]),
                "--cont-batching",
                "--cache-type-k", "q8_0",
                "--cache-type-v", "q4_0",
                "--jinja",
            ]
            print(f"🔧 Fallback cmd: ctx={min(cfg['context'], 2048)} | ngl=0")
            self.server_process = subprocess.Popen(
                fallback_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )
            self._wait_for_server_ready(timeout_seconds=120)

    def shutdown(self):
        """Stop the background server process."""
        if self.server_process:
            print("\n👋 Stopping llama-server...")
            if self.server_process.poll() is None:
                if os.name == 'nt':
                    # Windows: Force kill process tree
                    subprocess.call(['taskkill', '/F', '/T', '/PID', str(self.server_process.pid)])
                else:
                    os.killpg(os.getpgid(self.server_process.pid), signal.SIGTERM)
            
            self.server_process = None
            self._is_ready = False

    def warmup(self) -> None:
        """Send a tiny request to warm up the model (CUDA kernel compilation, page faults)."""
        if not self._is_ready:
            return
        try:
            print("🔥 Warming up model...")
            requests.post(
                f"http://{self.SERVER_HOST}:{self.SERVER_PORT}/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 1,
                    "temperature": 0,
                },
                timeout=30,
            )
            print("✅ Warmup complete")
        except Exception as e:
            print(f"⚠️  Warmup failed (non-fatal): {e}")

    JSON_GRAMMAR = r'''
root   ::= object
value  ::= object | array | string | number | ("true" | "false" | "null") ws

object ::=
  "{" ws (
            string ":" ws value
    ("," ws string ":" ws value)*
  )? "}" ws

array  ::=
  "[" ws (
            value
    ("," ws value)*
  )? "]" ws

string ::=
  "\"" (
    [^"\\\x7F\x00-\x1F] |
    "\\" (["\\/bfnrt] | "u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F])
  )* "\"" ws

number ::= ("-"? ([0-9] | [1-9] [0-9]*)) ("." [0-9]+)? ([eE] [-+]? [0-9]+)? ws

ws ::= ([ \t\n] ws)?
'''

    def cancel_generation(self) -> bool:
        """Cancel any in-flight generation. Critical for voice interruption support."""
        try:
            # llama-server supports slot-level cancellation
            requests.post(
                f"http://{self.SERVER_HOST}:{self.SERVER_PORT}/slots/0?action=erase",
                timeout=2,
            )
            return True
        except Exception:
            return False

    def chat(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: bool = False,
        json_mode: bool = False
    ):
        """
        Chat via llama-server's native OpenAI-compatible endpoint.
        Uses --jinja for correct per-model chat templates (no manual formatting).
        """
        if not self._is_ready:
            raise RuntimeError("Call setup() first!")

        token_limit = max_tokens or getattr(settings, "max_tokens", 512)
        temp = temperature if temperature is not None else getattr(settings, "temperature", 0.7)

        payload: Dict[str, Any] = {
            "messages": messages,
            "max_tokens": token_limit,
            "temperature": temp,
            "stream": stream,
            "top_p": 0.9,
            "repeat_penalty": 1.1,
        }

        if json_mode:
            payload["grammar"] = self.JSON_GRAMMAR

        timeout = 120 if token_limit > 500 else 60

        try:
            response = requests.post(
                f"http://{self.SERVER_HOST}:{self.SERVER_PORT}/v1/chat/completions",
                json=payload,
                stream=stream,
                timeout=timeout,
            )
            response.raise_for_status()

            if stream:
                return self._stream_response(response)

            data = response.json()
            content = data["choices"][0]["message"]["content"].strip()

            if json_mode:
                content = self._extract_json(content)

            return content

        except requests.Timeout:
            raise RuntimeError(f"Inference timed out after {timeout}s")
        except requests.RequestException as e:
            raise RuntimeError(f"Inference request failed: {e}")

    def generate(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        system_prompt: Optional[str] = None,
        stream: bool = False,
        json_mode: bool = False
    ):
        """Generate from a raw prompt by wrapping it as a chat message."""
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages, max_tokens, temperature, stream, json_mode)

    def _extract_json(self, text: str) -> str:
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            try:
                json.loads(json_match.group())
                return json_match.group()
            except json.JSONDecodeError:
                pass
        return text

    def _stream_response(self, response):
        """Yield streaming chunks from OpenAI-compatible SSE format."""
        for line in response.iter_lines():
            if not line:
                continue
            decoded = line.decode("utf-8")
            if not decoded.startswith("data: "):
                continue
            data_str = decoded[6:]
            if data_str.strip() == "[DONE]":
                return
            try:
                data = json.loads(data_str)
                delta = data.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    yield content
            except json.JSONDecodeError:
                pass

    @property
    def is_ready(self) -> bool:
        return self._is_ready and self.server_process is not None
    
    def get_status(self) -> Dict[str, Any]:
        return {
            "ready": self.is_ready,
            "model_path": str(self.model_path) if self.model_path else None,
            "server_pid": self.server_process.pid if self.server_process else None,
            "device": self.device_type,
            "hardware": self.hardware,
            "config": self.optimal_config,
        }
    
# -----------------------
# Singleton Instance
# -----------------------
_inference_service: Optional[InferenceService] = None
_singleton_lock = Lock()


def get_inference_service() -> InferenceService:
    global _inference_service
    if _inference_service is None:
        with _singleton_lock:
            if _inference_service is None:
                _inference_service = InferenceService()
    return _inference_service
