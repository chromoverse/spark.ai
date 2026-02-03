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
        
        # Check if already downloaded
        if model_path.exists() and any(model_path.iterdir()):
            logger.info(f"✅ Model '{model_key}' already exists at {model_path}")
            return True
        
        logger.info(f"⬇️  Downloading model '{model_key}' from {config['name']}...")
        
        try:
            model_path.mkdir(parents=True, exist_ok=True)
            
            if config["type"] == "sentence-transformer":
                from sentence_transformers import SentenceTransformer
                # Download directly to the target path
                model = SentenceTransformer(config["name"], cache_folder=str(model_path.parent))
                # Move to exact location if needed
                import shutil
                source = model_path.parent / config["name"].replace("/", "--")
                if source.exists() and source != model_path:
                    if model_path.exists():
                        shutil.rmtree(model_path)
                    shutil.move(str(source), str(model_path))
                
            elif config["type"] == "whisper":
                from faster_whisper import WhisperModel
                # faster-whisper uses size names, not full model names
                model_size = config["name"].split("/")[-1].replace("whisper-", "")
                # Just initialize - it will download automatically
                WhisperModel(model_size, download_root=str(model_path.parent), device="cpu")
                
            elif config["type"] == "transformers":
                from transformers import AutoModelForSequenceClassification, AutoTokenizer
                model = AutoModelForSequenceClassification.from_pretrained(config["name"])
                tokenizer = AutoTokenizer.from_pretrained(config["name"])
                model.save_pretrained(str(model_path))
                tokenizer.save_pretrained(str(model_path))
            
            
            logger.info(f"✅ Model '{model_key}' downloaded successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to download model '{model_key}': {e}")
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
                model_size = config["name"].split("/")[-1].replace("whisper-", "")
                compute_type = "float16" if config["device"] in ["cuda"] else "int8"
                model = WhisperModel(
                    model_size,
                    device=config["device"],
                    compute_type=compute_type,
                    download_root=str(model_path.parent)
                )
                
            elif config["type"] == "transformers":
                from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline
                model = pipeline(
                    "text-classification",
                    model=str(model_path),
                    tokenizer=str(model_path),
                    device=0 if config["device"] == "cuda" else -1
                )
                
            
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
            
            # Note: Kokoro TTS handles its own initialization separately
            
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