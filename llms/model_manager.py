import os
import json
import requests
from tqdm import tqdm
import subprocess


class ModelManager:
    def __init__(self, config_path="model_config.json", path_manager=None):
        """
        Initialize model manager with config and optional PathManager
        
        Args:
            config_path: Path to model_config.json
            path_manager: Optional PathManager instance
        """
        self.config = self._load_config(config_path)
        self.device_type = self._detect_device()
        
        # Use PathManager if provided, otherwise create one
        if path_manager:
            self.path_manager = path_manager
        else:
            from path_manager import PathManager
            self.path_manager = PathManager()
        
        # Get models directory from PathManager
        base_dir = self.path_manager.get_models_dir()
        self.models_dir = base_dir / self.config['settings']['models_base_dir']
        self.models_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"📁 Models directory: {self.models_dir}")
        
    def _load_config(self, config_path):
        """Load configuration from JSON file"""
        with open(config_path, 'r') as f:
            return json.load(f)
    
    def _detect_device(self):
        """Auto-detect if NVIDIA GPU is available"""
        if self.config['settings'].get('force_cpu', False):
            print("🔧 Force CPU mode enabled")
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
                print("✅ NVIDIA GPU detected")
                return 'gpu'
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        
        print("💻 CPU-only mode (no NVIDIA GPU found)")
        return 'cpu'
    
    def _download_file(self, url, destination):
        """Download file with progress bar"""
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
    
    def get_model_path(self, model_name="qwen2.5-7b", auto_download=True):
        """
        Get model path, download if missing
        
        Args:
            model_name: Name of model in config
            auto_download: If True, prompts to download missing models
            
        Returns:
            Path object to model file
        """
        if model_name not in self.config['models']:
            raise ValueError(f"Model '{model_name}' not found in config")
        
        model_config = self.config['models'][model_name][self.device_type]
        model_path = self.models_dir / model_config['filename']
        
        # Check if model exists
        if model_path.exists():
            print(f"✅ Model already exists: {model_path}")
            return model_path
        
        # Model doesn't exist
        if not auto_download:
            raise FileNotFoundError(f"Model not found: {model_path}")
        
        print(f"⚠️  Model not found: {model_path}")
        print(f"📦 Size: ~{model_config['size_gb']} GB")
        print(f"🎯 Device: {self.device_type.upper()}")
        print(f"🔢 Quantization: {model_config['quantization']}")
        
        user_input = input("Download now? (y/n): ").strip().lower()
        
        if user_input != 'y':
            raise FileNotFoundError("Model download cancelled by user")
        
        self._download_file(model_config['url'], model_path)
        
        return model_path
    
    def get_model_info(self, model_name="qwen2.5-7b"):
        """
        Get model information without downloading
        
        Args:
            model_name: Name of model in config
            
        Returns:
            Dictionary with model information
        """
        if model_name not in self.config['models']:
            raise ValueError(f"Model '{model_name}' not found in config")
        
        model_config = self.config['models'][model_name][self.device_type]
        model_path = self.models_dir / model_config['filename']
        
        return {
            'path': model_path,
            'exists': model_path.exists(),
            'device': self.device_type,
            'size_gb': model_config['size_gb'],
            'quantization': model_config['quantization'],
            'url': model_config['url']
        }


# Example usage
if __name__ == "__main__":
    from path_manager import PathManager
    
    # Initialize with PathManager
    path_mgr = PathManager()
    manager = ModelManager(path_manager=path_mgr)
    
    # Show model info
    info = manager.get_model_info()
    print("\n" + "="*50)
    print("MODEL INFORMATION")
    print("="*50)
    print(f"Device Type: {info['device']}")
    print(f"Model Path: {info['path']}")
    print(f"Exists: {info['exists']}")
    print(f"Size: ~{info['size_gb']} GB")
    print(f"Quantization: {info['quantization']}")
    print("="*50 + "\n")
    
    # Get model path (downloads if missing)
    try:
        model_path = manager.get_model_path()
        print(f"\n🎉 Ready to use: {model_path}")
    except FileNotFoundError as e:
        print(f"\n❌ {e}")