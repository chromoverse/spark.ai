"""
Qwen Inference using llama.cpp binary
Integrated with PathManager for production use
Auto-downloads llama.cpp binary if missing
"""

import subprocess
import os
import requests
import zipfile
from tqdm import tqdm
from path_manager import PathManager
from model_manager import ModelManager


class QwenInference:
    # llama.cpp release info
    LLAMA_CPP_VERSION = "b7664"
    LLAMA_CPP_RELEASES = {
        "Windows": {
            "url": "https://github.com/ggml-org/llama.cpp/releases/download/b7664/llama-b7664-bin-win-cpu-x64.zip",
            "executable": "llama-cli.exe",
            "size_mb": 35
        },
        "Darwin": {  # macOS
            "url": "https://github.com/ggml-org/llama.cpp/releases/download/b7664/llama-b7664-bin-macos-arm64.tar.gz",
            "executable": "llama-cli",
            "size_mb": 15
        },
        "Linux": {
            "url": "https://github.com/ggml-org/llama.cpp/releases/download/b7664/llama-b7664-bin-ubuntu-x64.tar.gz",
            "executable": "llama-cli",
            "size_mb": 35
        }
    }
    
    def __init__(self, path_manager=None):
        """
        Initialize Qwen inference engine
        
        Args:
            path_manager: Optional PathManager instance
        """
        # Use provided PathManager or create new one
        self.path_manager = path_manager or PathManager()
        
        # Initialize model manager with same PathManager
        self.model_manager = ModelManager(path_manager=self.path_manager)
        
        self.model_path = None
        self.llama_cli_path = None
        self.system = self.path_manager.system
        
    def _get_binaries_dir(self):
        """Get or create binaries directory in user data"""
        binaries_dir = self.path_manager.get_user_data_dir() / "binaries"
        binaries_dir.mkdir(parents=True, exist_ok=True)
        return binaries_dir
    
    def _download_llama_binary(self):
        """Download and extract llama.cpp binary for current OS"""
        if self.system not in self.LLAMA_CPP_RELEASES:
            raise NotImplementedError(f"No llama.cpp release available for {self.system}")
        
        release_info = self.LLAMA_CPP_RELEASES[self.system]
        binaries_dir = self._get_binaries_dir()
        
        print(f"\n⚠️  llama-cli not found. Downloading llama.cpp binary...")
        print(f"📦 Size: ~{release_info['size_mb']} MB")
        print(f"🎯 Platform: {self.system}")
        
        # Download file
        zip_path = binaries_dir / f"llama-{self.LLAMA_CPP_VERSION}.{'tar.gz' if self.system != 'Windows' else 'zip'}"
        
        print(f"⬇️  Downloading from GitHub releases...")
        response = requests.get(release_info['url'], stream=True)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        
        with open(zip_path, 'wb') as f, tqdm(
            desc="llama.cpp",
            total=total_size,
            unit='iB',
            unit_scale=True,
            unit_divisor=1024,
        ) as progress_bar:
            for chunk in response.iter_content(chunk_size=8192):
                size = f.write(chunk)
                progress_bar.update(size)
        
        # Extract archive
        print(f"📦 Extracting...")
        if self.system == "Windows":
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(binaries_dir)
        else:
            import tarfile
            with tarfile.open(zip_path, 'r:gz') as tar_ref:
                tar_ref.extractall(binaries_dir)
        
        # Find the executable
        exe_name = release_info['executable']
        extracted_exe = None
        
        # Search for the executable in extracted files
        for root, dirs, files in os.walk(binaries_dir):
            if exe_name in files:
                extracted_exe = binaries_dir / root / exe_name
                break
        
        if not extracted_exe:
            # Sometimes it's directly in binaries_dir
            extracted_exe = binaries_dir / exe_name
        
        # Clean up archive
        zip_path.unlink()
        
        if not extracted_exe.exists():
            raise FileNotFoundError(f"Could not find {exe_name} after extraction")
        
        print(f"✅ Downloaded: {extracted_exe}")
        return extracted_exe
    
    def setup(self, auto_download_binary=True):
        """
        Setup model and llama.cpp binary
        
        Args:
            auto_download_binary: If True, auto-download llama-cli if missing
        """
        # Get model path (downloads if needed)
        self.model_path = self.model_manager.get_model_path("qwen2.5-7b")
        
        # Look for llama-cli.exe in various locations
        bundle_dir = self.path_manager.get_bundle_dir()
        user_data_dir = self.path_manager.get_user_data_dir()
        binaries_dir = self._get_binaries_dir()
        
        exe_name = self.LLAMA_CPP_RELEASES[self.system]['executable']
        
        possible_paths = [
            bundle_dir / "tools" / exe_name,      # Bundled in production
            bundle_dir / exe_name,                # Development
            binaries_dir / exe_name,              # Downloaded to user data
            user_data_dir / "tools" / exe_name,   # Alternative user location
            f"./tools/{exe_name}",                # Current directory
            f"./{exe_name}"                       # Current directory
        ]
        
        for path in possible_paths:
            path_obj = path if hasattr(path, 'exists') else self.path_manager.get_bundle_dir() / path
            if path_obj.exists():
                self.llama_cli_path = path_obj
                break
        
        # If not found and auto_download enabled, download it
        if not self.llama_cli_path and auto_download_binary:
            try:
                self.llama_cli_path = self._download_llama_binary()
            except Exception as e:
                print(f"❌ Auto-download failed: {e}")
                print("\n📥 Manual download:")
                print("   https://github.com/ggerganov/llama.cpp/releases")
                print(f"   Extract {exe_name} to: {binaries_dir}")
                raise
        
        if not self.llama_cli_path:
            print("⚠️  llama-cli not found!")
            print("\n📥 Download from: https://github.com/ggerganov/llama.cpp/releases")
            print(f"   Look for: llama-*-bin-*-{self.system.lower()}*.zip")
            print("   Extract to one of these locations:")
            for path in possible_paths:
                print(f"     - {path}")
            raise FileNotFoundError(f"{exe_name} not found")
        
        print(f"✅ Model: {self.model_path}")
        print(f"✅ llama.cpp: {self.llama_cli_path}")
     
    def generate(self, prompt, max_tokens=512, temperature=0.7, system_prompt=None):
      """Generate response with real-time streaming"""
      if not self.model_path or not self.llama_cli_path:
          raise RuntimeError("Call setup() first!")
      
      full_prompt = prompt
      if system_prompt:
          full_prompt = f"{system_prompt}\n\n{prompt}"
      
      cmd = [
          str(self.llama_cli_path),
          "-m", str(self.model_path),
          "-p", full_prompt,
          "-n", str(max_tokens),
          "--temp", str(temperature),
          "-c", "32768",  # Context window: 32K tokens to support 20K+ input
          "-t", "8",
          "--no-display-prompt"
      ]
      
      print(f"\n🤖 Generating response...\n")
      print("-" * 50)
      
      # Run without capturing - output goes directly to console
      result = subprocess.run(cmd, timeout=120)
      
      print("-" * 50)
      
      if result.returncode != 0:
          print("❌ Generation failed")
          return None
      
      print("\n✅ Generation complete!")
      return "Response printed above"

    def chat(self, messages, max_tokens=512, temperature=0.7):
        """
        Chat-style inference with message history
        
        Args:
            messages: List of dicts with 'role' and 'content'
                     e.g., [{'role': 'user', 'content': 'Hello'}]
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            
        Returns:
            Generated response text
        """
        # Format messages into prompt
        prompt_parts = []
        for msg in messages:
            role = msg['role']
            content = msg['content']
            
            if role == 'system':
                prompt_parts.append(f"System: {content}")
            elif role == 'user':
                prompt_parts.append(f"User: {content}")
            elif role == 'assistant':
                prompt_parts.append(f"Assistant: {content}")
        
        prompt = "\n".join(prompt_parts) + "\nAssistant:"
        
        return self.generate(prompt, max_tokens, temperature)


# Example usage
if __name__ == "__main__":
    print("="*50)
    print("🚀 Qwen 2.5 7B Inference Test")
    print("="*50)
    
    # Initialize with PathManager
    path_mgr = PathManager()
    inference = QwenInference(path_manager=path_mgr)
    
    try:
        # Setup (checks model & llama.cpp)
        inference.setup()
        
        # Test 1: Simple generation
        print("\n" + "="*50)
        print("TEST 1: Simple Generation")
        print("="*50)
        
        prompt = "Write a Python function to calculate Fibonacci numbers recursively."
        print(f"\n📝 Prompt: {prompt}\n")
        print("-"*50)
        
        response = inference.generate(
            prompt=prompt,
            max_tokens=256,
            temperature=0.7
        )
        
        if response:
            print(f"\n💬 Response:\n{response}")
        
        # Test 2: Chat format
        print("\n" + "="*50)
        print("TEST 2: Chat Format")
        print("="*50)
        
        messages = [
            {'role': 'system', 'content': 'You are a helpful coding assistant.'},
            {'role': 'user', 'content': 'Explain what a decorator is in Python in one sentence.'}
        ]
        
        response = inference.chat(messages, max_tokens=128)
        
        if response:
            print(f"\n💬 Response:\n{response}")
        
        print("\n" + "="*50)
        print("✅ ALL TESTS PASSED")
        print("="*50)
            
    except FileNotFoundError as e:
        print(f"\n❌ {e}")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()