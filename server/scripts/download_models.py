#!/usr/bin/env python3
"""
Download Models Script
Downloads all ML models before starting the server
Run this during Docker build or before first run
"""
import sys
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ml.model_loader import model_loader
from app.ml.config import MODELS_CONFIG, DEVICE

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

logger = logging.getLogger(__name__)

def main():
    """Download all models"""
    logger.info("=" * 60)
    logger.info("🤖 AI Model Downloader")
    logger.info("=" * 60)
    logger.info(f"📍 Device: {DEVICE}")
    logger.info(f"📦 Models to download: {len(MODELS_CONFIG)}")
    
    for model_key, config in MODELS_CONFIG.items():
        logger.info(f"  - {model_key}: {config['name']}")
    
    logger.info("=" * 60)
    
    # Download all models
    success = model_loader.download_all_models()
    
    logger.info("=" * 60)
    if success:
        logger.info("✅ All models downloaded successfully!")
        logger.info("🚀 You can now start your server")
        return 0
    else:
        logger.error("❌ Some models failed to download")
        logger.error("Please check the errors above and try again")
        return 1


if __name__ == "__main__":
    sys.exit(main())