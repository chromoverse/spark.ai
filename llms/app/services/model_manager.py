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
        model_path = manager.get_model_path("gemma-4-e4b")
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
        models_subdir = self.config.get('settings', {}).get('models_base_dir', 'reasoning_models')
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
        """Auto-detect GPU: NVIDIA (CUDA) > AMD/Intel (Vulkan) > CPU."""
        if self.config.get('settings', {}).get('force_cpu', False):
            print("🔧 Force CPU mode enabled in config")
            return 'cpu'

        from app.services.inference_service import detect_hardware
        hw = detect_hardware()
        device = hw["device"]
        gpu_name = hw.get("gpu_name", "")
        print(f"✅ Detected device: {device.upper()}" + (f" ({gpu_name})" if gpu_name else ""))
        return device

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
        model_name: str = "gemma-4-e4b",
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
        
        # Detect hardware for smart model selection
        ram_gb = 8.0
        vram_mb = 0
        try:
            import psutil
            ram_gb = psutil.virtual_memory().total / (1024**3)
        except ImportError:
            pass

        from app.services.inference_service import detect_hardware
        hw = detect_hardware()
        vram_mb = hw.get("vram_mb", 0)
        device = hw.get("device", self.device_type)

        # Metal has its own quant tier in config (Q8_0 since unified memory is fast)
        quant_key = "metal" if device == "metal" else self.device_type

        # Step 1: Downgrade model size if hardware can't handle it
        if model_name == "gemma-4-e4b":
            candidate = self.config['models'][model_name].get(quant_key, {})
            model_size_mb = candidate.get("size_gb", 99) * 1024

            too_big_for_ram = ram_gb < 10
            too_big_for_vram = vram_mb > 0 and model_size_mb > vram_mb * 0.85

            if too_big_for_ram or too_big_for_vram:
                reason = f"RAM {ram_gb:.0f}GB" if too_big_for_ram else f"VRAM {vram_mb}MB < model {model_size_mb:.0f}MB"
                print(f"⚠️  {reason}: switching to gemma-4-e2b")
                model_name = "gemma-4-e2b"

        # Step 2: Pick quantization — downgrade to Q4_K_M if model still too big for VRAM
        candidate = self.config['models'][model_name].get(quant_key, {})
        model_size_mb = candidate.get("size_gb", 99) * 1024

        if vram_mb > 0 and model_size_mb > vram_mb * 0.85 and quant_key != "cpu":
            print(f"⚠️  Model {model_size_mb:.0f}MB > VRAM {vram_mb}MB: using Q4_K_M")
            quant_key = "cpu"

        # Step 3: On low-RAM systems with iGPU, always use smallest quantization
        if ram_gb < 10 and device == "vulkan":
            quant_key = "cpu"

        model_config = self.config['models'][model_name][quant_key]
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

    def get_model_info(self, model_name: str = "gemma-4-e4b") -> Dict[str, Any]:
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
