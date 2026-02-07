"""
Model Manager Service
---------------------
Manages LLM model downloads and device detection.
Supports both CPU and GPU optimized models.

Features:
    - Auto-detection of NVIDIA GPU
    - Automatic model download with progress bar
    - Model versioning via config file
    - Extensible for future models (vision, etc.)
"""

import os
import json
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any

import requests
from tqdm import tqdm

from app.services.path_manager import PathManager, get_path_manager
from app.core.config import get_config_path


class ModelManager:
    """
    Manages model downloads and device-specific model selection.
    
    Features:
        - GPU/CPU auto-detection
        - Automatic downloads with progress
        - Non-interactive mode for server use
    
    Usage:
        manager = ModelManager()
        model_path = manager.get_model_path("qwen2.5-7b")
    """

    def __init__(
        self,
        config_path: Optional[Path] = None,
        path_manager: Optional[PathManager] = None,
        interactive: bool = False
    ):
        """
        Initialize model manager.
        
        Args:
            config_path: Path to model_config.json
            path_manager: PathManager instance (uses singleton if None)
            interactive: If True, prompt user before downloads
        """
        self.config_path = config_path or get_config_path()
        self.config = self._load_config()
        self.device_type = self._detect_device()
        self.interactive = interactive
        
        # Use provided PathManager or singleton
        self.path_manager = path_manager or get_path_manager()
        
        # Setup models directory
        base_dir = self.path_manager.get_models_dir()
        models_subdir = self.config.get('settings', {}).get('models_base_dir', 'qwen')
        self.models_dir = base_dir / models_subdir
        self.models_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"📁 Models directory: {self.models_dir}")

    def _load_config(self) -> Dict[str, Any]:
        """
        Load model configuration from JSON file.
        
        Returns:
            Configuration dictionary
            
        Raises:
            FileNotFoundError: If config file doesn't exist
        """
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config not found: {self.config_path}")
            
        with open(self.config_path, 'r') as f:
            return json.load(f)

    def _detect_device(self) -> str:
        """
        Auto-detect if NVIDIA GPU is available.
        
        Returns:
            'gpu' if NVIDIA GPU found, 'cpu' otherwise
        """
        # Check if forced to CPU mode
        if self.config.get('settings', {}).get('force_cpu', False):
            print("🔧 Force CPU mode enabled in config")
            return 'cpu'
        
        try:
            # Check for NVIDIA GPU using nvidia-smi
            result = subprocess.run(
                ['nvidia-smi'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=3
            )
            if result.returncode == 0:
                print("✅ NVIDIA GPU detected - using GPU-optimized model")
                return 'gpu'
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
            
        # Check for AMD/Intel GPUs using wmic (Windows)
        try:
            cmd = "wmic path win32_VideoController get name"
            result = subprocess.run(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                text=True,
                shell=True
            )
            output = result.stdout.lower()
            if "amd" in output or "radeon" in output or "intel" in output:
                 print(f"✅ Vulkan-compatible GPU detected: {output.strip().splitlines()[-1]}")
                 return 'vulkan'
        except Exception as e:
            print(f"⚠️ GPU detection failed: {e}")
        
        print("💻 CPU mode (no NVIDIA/AMD/Intel GPU detected)")
        return 'cpu'

    def _download_file(self, url: str, destination: Path) -> None:
        """
        Download file with progress bar.
        
        Args:
            url: Download URL
            destination: Local file path
        """
        print(f"⬇️  Downloading from {url}")
        
        response = requests.get(url, stream=True)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        
        with open(destination, 'wb') as f, tqdm(
            desc=destination.name,
            total=total_size,
            unit='iB',
            unit_scale=True,
            unit_divisor=1024,
        ) as progress_bar:
            for chunk in response.iter_content(chunk_size=8192):
                size = f.write(chunk)
                progress_bar.update(size)
        
        print(f"✅ Downloaded: {destination}")

    def get_model_path(
        self,
        model_name: str = "qwen2.5-7b",
        auto_download: bool = True
    ) -> Path:
        """
        Get model path, downloading if necessary.
        
        Args:
            model_name: Model identifier from config
            auto_download: If True, download missing models
            
        Returns:
            Path to model file
            
        Raises:
            ValueError: If model not found in config
            FileNotFoundError: If model missing and auto_download=False
        """
        if model_name not in self.config.get('models', {}):
            raise ValueError(f"Model '{model_name}' not found in config")
        
        # Fallback to tiny model on CPU for performance
        if self.device_type == 'cpu' and model_name == "qwen2.5-7b":
            print("⚠️  CPU detected: Switching to qwen2.5-1.5b for better performance")
            model_name = "qwen2.5-1.5b"

        model_config = self.config['models'][model_name][self.device_type]
        model_path = self.models_dir / model_config['filename']
        
        # Check if model already exists
        if model_path.exists():
            print(f"✅ Model ready: {model_path}")
            return model_path
        
        # Model doesn't exist
        if not auto_download:
            raise FileNotFoundError(f"Model not found: {model_path}")
        
        print(f"⚠️  Model not found: {model_path}")
        print(f"📦 Size: ~{model_config['size_gb']} GB")
        print(f"🎯 Device: {self.device_type.upper()}")
        print(f"🔢 Quantization: {model_config['quantization']}")
        
        # Interactive mode: ask for confirmation
        if self.interactive:
            user_input = input("Download now? (y/n): ").strip().lower()
            if user_input != 'y':
                raise FileNotFoundError("Model download cancelled by user")
        else:
            print("📥 Starting automatic download...")
        
        self._download_file(model_config['url'], model_path)
        return model_path

    def get_model_info(self, model_name: str = "qwen2.5-7b") -> Dict[str, Any]:
        """
        Get model information without downloading.
        
        Args:
            model_name: Model identifier from config
            
        Returns:
            Dict with path, exists, device, size_gb, quantization, url
        """
        if model_name not in self.config.get('models', {}):
            raise ValueError(f"Model '{model_name}' not found in config")
        
        model_config = self.config['models'][model_name][self.device_type]
        model_path = self.models_dir / model_config['filename']
        
        return {
            'name': model_name,
            'path': model_path,
            'exists': model_path.exists(),
            'device': self.device_type,
            'size_gb': model_config['size_gb'],
            'quantization': model_config['quantization'],
            'url': model_config['url']
        }

    def list_available_models(self) -> Dict[str, Dict[str, Any]]:
        """
        List all available models from config.
        
        Returns:
            Dict of model_name -> model_info
        """
        result = {}
        for model_name in self.config.get('models', {}).keys():
            result[model_name] = self.get_model_info(model_name)
        return result


# -----------------------
# Singleton Instance
# -----------------------
_model_manager: Optional[ModelManager] = None


def get_model_manager() -> ModelManager:
    """
    Get singleton ModelManager instance.
    
    Returns:
        ModelManager singleton
    """
    global _model_manager
    if _model_manager is None:
        _model_manager = ModelManager()
    return _model_manager
