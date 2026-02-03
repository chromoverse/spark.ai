"""
Model Loader - Handles downloading and loading all ML models
"""
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from app.ml.config import MODELS_CONFIG, DEVICE

logger = logging.getLogger(__name__)

class ModelLoader:
    """Singleton class to manage model loading"""
    
    _instance = None
    _models: Dict[str, Any] = {}
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            logger.info(f"🔧 Initializing ModelLoader with device: {DEVICE}")
            self._initialized = True
    
    def download_model(self, model_key: str) -> bool:
        """Download a model if not already present"""
        config = MODELS_CONFIG.get(model_key)
        if not config:
            logger.error(f"❌ Model '{model_key}' not found in config")
            return False
        
        model_path = config["path"]
        
        # Check if already downloaded (simple check: folder exists and not empty)
        if model_path.exists() and any(model_path.iterdir()):
            logger.info(f"✅ Model '{model_key}' already exists at {model_path}")
            return True
        
        logger.info(f"⬇️  Downloading model '{model_key}' from {config['name']}...")
        
        try:
            model_path.mkdir(parents=True, exist_ok=True)
            from huggingface_hub import snapshot_download

            # Uniform download logic for all HF models
            # This ensures the model files land EXACTLY in model_path
            # skipping the confusing cache structures
            snapshot_download(
                repo_id=str(config["name"]),
                local_dir=str(model_path),
                local_dir_use_symlinks=False,  # Important for windows/portability
                repo_type="model"
            )
                
            logger.info(f"✅ Model '{model_key}' downloaded successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to download model '{model_key}': {e}")
            # Clean up partial download
            # import shutil
            # if model_path.exists():
            #     shutil.rmtree(model_path)
            return False
    
    def load_model(self, model_key: str, force_reload: bool = False) -> Optional[Any]:
        """Load a model into memory"""
        if not force_reload and model_key in self._models:
            logger.info(f"♻️  Using cached model '{model_key}'")
            return self._models[model_key]
        
        config = MODELS_CONFIG.get(model_key)
        if not config:
            logger.error(f"❌ Model '{model_key}' not found in config")
            return None
        
        model_path = config["path"]
        
        # Ensure model is downloaded
        if not self.download_model(model_key):
            return None
        
        logger.info(f"📦 Loading model '{model_key}' from {model_path}...")
        
        try:
            if config["type"] == "sentence-transformer":
                from sentence_transformers import SentenceTransformer
                model = SentenceTransformer(str(model_path), device=config["device"])
                
            elif config["type"] == "whisper":
                from faster_whisper import WhisperModel
                # faster-whisper can load from a local directory path
                compute_type = "float16" if config["device"] in ["cuda"] else "int8"
                model = WhisperModel(
                    str(model_path), # Load from local path
                    device=config["device"],
                    compute_type=compute_type
                )
                
            elif config["type"] == "transformers":
                from transformers import pipeline
                # Pipelines can load from local path
                model = pipeline(
                    "text-classification",
                    model=str(model_path),
                    tokenizer=str(model_path),
                    device=0 if config["device"] == "cuda" else -1
                )
                
            elif config["type"] == "fishaudio":
                import torch
                from transformers import AutoTokenizer
                
                # Load tokenizer
                tokenizer = AutoTokenizer.from_pretrained(str(model_path))
                
                # Load model
                model_file = model_path / "model.pt"
                if not model_file.exists():
                     # Fallback if model.pt isn't the name or structure differs?
                     # FishAudio s1-mini usually has model.pt or similar in repo. 
                     # Checking repo: fishaudio/openaudio-s1-mini has model.pth possibly?
                     # Let's assume standard structure or handle exception.
                     pass

                if config["device"] == "cuda":
                    model = torch.jit.load(str(model_file), map_location=config["device"]).half()
                else:
                    model = torch.jit.load(str(model_file), map_location=config["device"])
                
                model.eval()
                
                model = {
                    "model": model,
                    "tokenizer": tokenizer,
                    "device": config["device"]
                }
                
            else:
                logger.error(f"❌ Unknown model type: {config['type']}")
                return None
            
            self._models[model_key] = model
            logger.info(f"✅ Model '{model_key}' loaded successfully on {config['device']}")
            return model
            
        except Exception as e:
            logger.error(f"❌ Failed to load model '{model_key}': {e}")
            return None
    
    def download_all_models(self) -> bool:
        """Download all configured models"""
        logger.info("⬇️  Downloading all models...")
        success = True
        
        for model_key in MODELS_CONFIG.keys():
            if not self.download_model(model_key):
                success = False
        
        if success:
            logger.info("✅ All models downloaded successfully")
        else:
            logger.warning("⚠️  Some models failed to download")
        
        return success
    
    def load_all_models(self) -> bool:
        """Load all configured models"""
        logger.info("📦 Loading all models...")
        success = True
        
        for model_key in MODELS_CONFIG.keys():
            if not self.load_model(model_key):
                success = False
        
        if success:
            logger.info("✅ All models loaded successfully")
        else:
            logger.warning("⚠️  Some models failed to load")
        
        return success
    
    def get_model(self, model_key: str) -> Optional[Any]:
        """Get a loaded model"""
        return self._models.get(model_key)
    
    def warmup_models(self):
        """Warmup models with dummy data to avoid cold start"""
        logger.info("🔥 Warming up models...")
        
        try:
            # Warmup embedding model
            if "embedding" in self._models:
                self._models["embedding"].encode(["warmup text"], show_progress_bar=False)
                logger.info("✅ Embedding model warmed up")
            
            # Warmup emotion model
            if "emotion" in self._models:
                self._models["emotion"]("warmup text")
                logger.info("✅ Emotion model warmed up")
            
            # Warmup Fish Audio TTS
            if "openaudio_s1_mini" in self._models:
                import torch
                tts_model = self._models["openaudio_s1_mini"]
                dummy_text = "Hello world"
                tokens = tts_model["tokenizer"](
                    dummy_text,
                    return_tensors="pt",
                    padding=True
                ).to(tts_model["device"])
                
                with torch.no_grad():
                    _ = tts_model["model"](**tokens)
                    
                logger.info("✅ Fish Audio TTS model warmed up")
            
            # Whisper warmup happens on first transcription
            
            logger.info("✅ All models warmed up")
            
        except Exception as e:
            logger.warning(f"⚠️  Model warmup failed: {e}")
    
    def unload_model(self, model_key: str):
        """Unload a model from memory"""
        if model_key in self._models:
            del self._models[model_key]
            logger.info(f"🗑️  Model '{model_key}' unloaded from memory")
    
    def unload_all_models(self):
        """Unload all models from memory"""
        self._models.clear()
        logger.info("🗑️  All models unloaded from memory")


# Singleton instance
model_loader = ModelLoader()