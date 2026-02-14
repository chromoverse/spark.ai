"""
Inference Service
-----------------
LLM inference using llama.cpp server.
Singleton service with persistent model loading for low latency.

Features:
    - Auto-download llama.cpp binaries
    - Persistent server process management
    - GPU/CPU device detection
    - OpenAI-compatible API client
    - Thread-safe singleton
"""

import os
import subprocess
import zipfile
import time
import signal
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from threading import Lock

import requests
from tqdm import tqdm

from app.services.path_manager import PathManager, get_path_manager
from app.services.model_manager import ModelManager, get_model_manager
from app.core.config import settings


class InferenceService:
    """
    LLM Inference Service using llama-server.
    
    Provides:
        - Persistent background server for instant inference
        - Model and binary setup with auto-download
        - Chat-style inference with message history
    
    Usage:
        service = InferenceService()
        service.setup()
        response = service.chat([{"role": "user", "content": "Hello"}])
        service.shutdown()
    """

    # llama.cpp release configuration
    LLAMA_CPP_VERSION = "b7664"
    LLAMA_CPP_RELEASES = {
        "Windows": {
            "cpu": {
                "url": "https://github.com/ggml-org/llama.cpp/releases/download/b7664/llama-b7664-bin-win-cpu-x64.zip  ",
                "executable": "llama-server.exe",
                "size_mb": 35
            },
            "gpu": {
                "url": "https://github.com/ggml-org/llama.cpp/releases/download/b7664/llama-b7664-bin-win-cuda-cu12.2.0-x64.zip  ",
                "executable": "llama-server.exe",
                "size_mb": 450
            },
            "vulkan": {
                "url": "https://github.com/ggml-org/llama.cpp/releases/download/b7664/llama-b7664-bin-win-vulkan-x64.zip  ",
                "executable": "llama-server.exe",
                "size_mb": 40
            }
        },
        "Darwin": {  # macOS
            "cpu": {
                "url": "https://github.com/ggml-org/llama.cpp/releases/download/b7664/llama-b7664-bin-macos-arm64.tar.gz  ",
                "executable": "llama-server",
                "size_mb": 15
            },
            "gpu": None  # macOS uses Metal, same binary
        },
        "Linux": {
            "cpu": {
                "url": "https://github.com/ggml-org/llama.cpp/releases/download/b7664/llama-b7664-bin-ubuntu-x64.tar.gz  ",
                "executable": "llama-server",
                "size_mb": 35
            },
            "gpu": {
                "url": "https://github.com/ggml-org/llama.cpp/releases/download/b7664/llama-b7664-bin-ubuntu-x64-cuda.tar.gz  ",
                "executable": "llama-server",
                "size_mb": 400
            },
            "vulkan": {
                "url": "https://github.com/ggml-org/llama.cpp/releases/download/b7664/llama-b7664-bin-ubuntu-x64.tar.gz  ", # Usually packaged in main or separate
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
        """
        Initialize inference service.
        
        Args:
            path_manager: PathManager instance (uses singleton if None)
            model_manager: ModelManager instance (uses singleton if None)
        """
        self.path_manager = path_manager or get_path_manager()
        self.model_manager = model_manager or get_model_manager()
        
        self.model_path: Optional[Path] = None
        self.server_path: Optional[Path] = None
        self.server_process: Optional[subprocess.Popen] = None
        
        self.system = self.path_manager.system
        self.device_type = self.model_manager.device_type
        self._is_ready = False
        self._lock = Lock()

    def _get_release_info(self) -> Dict[str, Any]:
        """Get llama.cpp release info for current OS and device."""
        os_releases = self.LLAMA_CPP_RELEASES.get(self.system, {})
        release = os_releases.get(self.device_type)
        if release is None:
            # Fallbacks
            if self.device_type == 'vulkan' and self.system == 'Linux':
                 # Linux binaries typically include checking or we map to cpu if missing explicit vulkan build
                 release = os_releases.get('cpu')
            else:
                 release = os_releases.get('cpu')
        
        if release is None:
            raise NotImplementedError(
                f"No llama.cpp release for {self.system}/{self.device_type}"
            )
        return release

    def _download_llama_binary(self) -> Path:
        """Download and extract llama.cpp binary."""
        release_info = self._get_release_info()
        binaries_dir = self.path_manager.get_binaries_dir()
        
        print(f"\n⚠️  llama-server not found. Downloading llama.cpp binary...")
        print(f"📦 Size: ~{release_info['size_mb']} MB")
        print(f"🎯 Platform: {self.system} ({self.device_type.upper()})")
        
        url = release_info['url']
        is_zip = url.endswith('.zip')
        ext = '.zip' if is_zip else '.tar.gz'
        
        # Unique name for vulkan vs cpu to prevent overwrites if switching
        variant = f"-{self.device_type}" if self.device_type != 'cpu' else ""
        archive_path = binaries_dir / f"llama-{self.LLAMA_CPP_VERSION}{variant}{ext}"
        
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
        if is_zip:
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                zip_ref.extractall(binaries_dir)
        else:
            import tarfile
            with tarfile.open(archive_path, 'r:gz') as tar_ref:
                tar_ref.extractall(binaries_dir)
        
        exe_name = release_info['executable']
        extracted_exe = None
        for root, dirs, files in os.walk(binaries_dir):
            if exe_name in files:
                extracted_exe = Path(root) / exe_name
                break
        
        archive_path.unlink()
        
        if not extracted_exe or not extracted_exe.exists():
            raise FileNotFoundError(f"Could not find {exe_name} after extraction")
        
        print(f"✅ Downloaded: {extracted_exe}")
        return extracted_exe

    def _find_llama_binary(self) -> Optional[Path]:
        """Search for llama-server in known locations."""
        release_info = self._get_release_info()
        exe_name = release_info['executable']
        
        bundle_dir = self.path_manager.get_bundle_dir()
        binaries_dir = self.path_manager.get_binaries_dir()
        
        search_locations = [
            bundle_dir / "tools" / exe_name,
            bundle_dir / exe_name,
            binaries_dir / exe_name,
        ]
        
        for root, dirs, files in os.walk(binaries_dir):
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

    def _start_server(self):
        """Start the llama-server background process."""
        print("⏳ Starting llama-server process...")
        
        # Determine GPU layers based on device
        n_gpu_layers = "0"
        if self.device_type in ["gpu", "vulkan"]:
            n_gpu_layers = "99"
            
        print(f"🔧 Device: {self.device_type.upper()} (GPU Layers: {n_gpu_layers})")
        
        cmd = [
            str(self.server_path),
            "-m", str(self.model_path),
            "--host", self.SERVER_HOST,
            "--port", str(self.SERVER_PORT),
            "-c", "32768",  # Context window: 32K tokens to support 20K+ input
            "--n-gpu-layers", n_gpu_layers
        ]
        
        # Start detached process
        # We don't capture stdout/stderr to avoid buffer deadlocks
        # They will be inherited by the parent process (visible in console)
        self.server_process = subprocess.Popen(
            cmd,
            # stdout=subprocess.PIPE,  <-- Caused buffer overflow/deadlock
            # stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
        )
        
        # Wait for health check
        print("⏳ Waiting for server to become healthy...", end="", flush=True)
        max_retries = 600  # 10 minutes
        for i in range(max_retries):
            # Check if process died
            if self.server_process.poll() is not None:
                print(f"\n❌ Server process died with code {self.server_process.returncode}")
                self.shutdown()
                raise RuntimeError("llama-server process died unexpectedly")

            try:
                response = requests.get(f"http://{self.SERVER_HOST}:{self.SERVER_PORT}/health", timeout=1)
                if response.status_code == 200:
                    print(" Done!")
                    return
                # Optional: debug print for other codes
                if i % 10 == 0:  # Print every 10s
                   print(f"({response.status_code})", end="", flush=True)
                
                # Server is running but not ready (e.g. 503)
                time.sleep(1)
            except requests.RequestException:
                time.sleep(1)
                print(".", end="", flush=True)
        
        # If we get here, server didn't start
        self.shutdown()
        raise RuntimeError("Timed out waiting for llama-server to start")

    def shutdown(self):
        """Stop the background server process."""
        if self.server_process:
            print("\n👋 Stopping llama-server...")
            if os.name == 'nt':
                # Windows: Force kill process tree
                subprocess.call(['taskkill', '/F', '/T', '/PID', str(self.server_process.pid)])
            else:
                os.killpg(os.getpgid(self.server_process.pid), signal.SIGTERM)
            
            self.server_process = None
            self._is_ready = False

    def warmup(self) -> None:
        """Warmup is automatic with server mode."""
        pass

    # JSON Grammar for llama.cpp - ensures valid JSON output
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
    
    def generate(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        system_prompt: Optional[str] = None,
        stream: bool = False,
        json_mode: bool = False
    ):
        """
        Generate response via HTTP API.
        
        Args:
            prompt: The input prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (lower = more deterministic)
            system_prompt: Optional system prompt to prepend
            stream: Whether to stream the response
            json_mode: If True, enforces JSON output using grammar
        """
        if not self._is_ready:
            raise RuntimeError("Call setup() first!")
            
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        
        # Balanced stop sequences - not too aggressive
        stop_sequences = [
            "</s>",              # EOS token
            "<|im_end|>",        # Chat format end
            "<|endoftext|>",     # GPT-style end
            "<|eot_id|>",        # Llama-3 specific
            "\n\nUser:",         # Conversation restart
            "\n\nAssistant:",    # Duplicate assistant
            "\n\n\n",            # Triple newline (likely garbage)
        ]
        
        # FIXED: Remove strict 150 token limit
        # Use requested max_tokens or fallback to settings
        token_limit = max_tokens or getattr(settings, 'max_tokens', 512)
        
        payload = {
            "prompt": full_prompt,
            "n_predict": token_limit,  # FIXED: No artificial cap
            "temperature": temperature or getattr(settings, 'temperature', 0.7),
            "stop": stop_sequences,
            "stream": stream,
            "repeat_penalty": 1.15,     # Moderate - prevent loops
            "frequency_penalty": 0.3,   # Reduced - was too aggressive
            "presence_penalty": 0.3,    # Reduced - was too aggressive
            "top_p": 0.9,
            "top_k": 40,
        }
        
        if json_mode:
            payload["grammar"] = self.JSON_GRAMMAR
        
        try:
            # FIXED: Increased timeout for large contexts
            timeout = 120 if token_limit > 500 else 60
            
            response = requests.post(
                f"http://{self.SERVER_HOST}:{self.SERVER_PORT}/completion",
                json=payload,
                stream=stream,
                timeout=timeout
            )
            response.raise_for_status()
            
            if stream:
                return self._stream_response(response)
            else:
                content = response.json().get('content', '').strip()
                
                # Light cleanup - remove only obvious garbage
                content = content.replace("</s>", "").replace("<s>", "").strip()
                
                # Don't aggressively cut at prompt markers
                # Only remove if they appear at the very end
                garbage_endings = ["# USER SAYS", "# QUERY", "User:", "Assistant:"]
                for marker in garbage_endings:
                    if content.endswith(marker):
                        content = content[:-len(marker)].strip()
                
                if json_mode:
                    content = self._extract_json(content)
                
                return content
                
        except requests.Timeout:
            raise RuntimeError(f"Inference timed out after {timeout}s")
        except requests.RequestException as e:
            raise RuntimeError(f"Inference request failed: {e}")
        except Exception as e:
            print(f"❌ Inference error: {e}")
            raise RuntimeError(f"Inference failed: {e}")

    def _extract_json(self, text: str) -> str:
        """Extract clean JSON from response, removing any garbage."""
        import re
        
        # Try to find JSON object
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            try:
                # Validate it's proper JSON
                json.loads(json_match.group())
                return json_match.group()
            except json.JSONDecodeError:
                pass
        
        # Return original if no valid JSON found
        return text

    def _stream_response(self, response):
        """Yield streaming chunks with light garbage filtering."""
        accumulated = ""
        
        # Only critical stop tokens
        critical_stops = ["</s>", "<|eot_id|>", "<|im_end|>"]
        
        for line in response.iter_lines():
            if line:
                decoded_line = line.decode('utf-8')
                if decoded_line.startswith('data: '):
                    json_str = decoded_line[6:]
                    try:
                        data = json.loads(json_str)
                        content = data.get('content', '')
                        
                        if not content:
                            continue
                        
                        accumulated += content
                        
                        # Stop only on critical tokens
                        for token in critical_stops:
                            if token in accumulated:
                                clean = accumulated.split(token)[0].strip()
                                if clean:  # FIXED: Removed arbitrary length check
                                    yield clean
                                return
                        
                        # Yield normally
                        yield content
                        
                    except json.JSONDecodeError:
                        pass

    def chat(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: bool = False,
        json_mode: bool = False
    ):
        """
        Chat inference optimized for Llama models.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            stream: Whether to stream the response
            json_mode: If True, enforces JSON output using grammar
        """
        # Build clean prompt
        system_content = ""
        conversation = []
        
        for msg in messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            
            if role == 'system':
                system_content = content
            elif role == 'user':
                conversation.append(f"User: {content}")
            elif role == 'assistant':
                conversation.append(f"Assistant: {content}")
        
        # Build final prompt
        if system_content:
            prompt = f"{system_content}\n\n" + "\n".join(conversation) + "\nAssistant:"
        else:
            prompt = "\n".join(conversation) + "\nAssistant:"
        
        return self.generate(
            prompt, 
            max_tokens, 
            temperature, 
            stream=stream, 
            json_mode=json_mode
        )

    @property
    def is_ready(self) -> bool:
        return self._is_ready and self.server_process is not None
    
    def get_status(self) -> Dict[str, Any]:
        return {
            "ready": self.is_ready,
            "model_path": str(self.model_path) if self.model_path else None,
            "server_pid": self.server_process.pid if self.server_process else None,
            "device": self.device_type
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