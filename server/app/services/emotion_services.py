"""
Emotion Detection Service
Single source of truth for emotion analysis
"""
import logging
from typing import Union, List, Dict, Any

from app.ml import model_loader, DEVICE

logger = logging.getLogger(__name__)


class EmotionService:
    """Unified emotion detection service using ML model loader"""
    
    def __init__(self):
        self.model = None
        self._ensure_model_loaded()
    
    def _ensure_model_loaded(self):
        """Ensure emotion model is loaded"""
        if self.model is None:
            self.model = model_loader.get_model("emotion")
            if self.model is None:
                logger.warning("⚠️ Emotion model not loaded, attempting to load...")
                self.model = model_loader.load_model("emotion")
            
            if self.model:
                logger.info("✅ Emotion service ready")
    
    def detect(self, text: str) -> str:
        """
        Detect dominant emotion from text (simple)
        
        Args:
            text: Input text
            
        Returns:
            Emotion label (e.g., "joy", "sadness", "anger")
        
        Usage:
            emotion = emotion_service.detect("I'm so happy!")
            # Returns: "joy"
        """
        self._ensure_model_loaded()
        
        if not self.model:
            logger.error("❌ Emotion model not available")
            return "neutral"
        
        try:
            result = self.model(text)
            
            if result and len(result) > 0:
                emotion = result[0]["label"].lower()
                logger.debug(f"Detected emotion: {emotion} for text: '{text[:50]}...'")
                return emotion
            
            return "neutral"
            
        except Exception as e:
            logger.error(f"❌ Emotion detection failed: {e}")
            return "neutral"
    
    def detect_detailed(self, text: str) -> Dict[str, Any]:
        """
        Detect emotion with confidence score (detailed)
        
        Args:
            text: Input text
            
        Returns:
            Dict with emotion, confidence, and original text
        
        Usage:
            result = emotion_service.detect_detailed("I'm so happy!")
            # Returns: {"emotion": "joy", "confidence": 0.98, "text": "..."}
        """
        self._ensure_model_loaded()
        
        if not self.model:
            logger.error("❌ Emotion model not available")
            return {
                "success": False,
                "emotion": "neutral",
                "confidence": 0.0,
                "text": text,
                "error": "Model not available"
            }
        
        try:
            result = self.model(text)
            
            if result and len(result) > 0:
                emotion_data = result[0]
                emotion = emotion_data["label"].lower()
                confidence = emotion_data["score"]
                
                logger.info(f"Detected: {emotion} ({confidence:.2f}) for '{text[:30]}...'")
                
                return {
                    "success": True,
                    "emotion": emotion,
                    "confidence": round(confidence, 4),
                    "text": text
                }
            
            return {
                "success": False,
                "emotion": "neutral",
                "confidence": 0.0,
                "text": text,
                "error": "No result returned"
            }
            
        except Exception as e:
            logger.error(f"❌ Emotion detection failed: {e}")
            return {
                "success": False,
                "emotion": "neutral",
                "confidence": 0.0,
                "text": text,
                "error": str(e)
            }
    
    def detect_batch(self, texts: List[str]) -> List[str]:
        """
        Detect emotions for multiple texts (simple)
        
        Args:
            texts: List of input texts
            
        Returns:
            List of emotion labels
        
        Usage:
            emotions = emotion_service.detect_batch(["I'm happy", "I'm sad"])
            # Returns: ["joy", "sadness"]
        """
        self._ensure_model_loaded()
        
        if not self.model:
            logger.error("❌ Emotion model not available")
            return ["neutral"] * len(texts)
        
        try:
            results = self.model(texts)
            emotions = [result["label"].lower() for result in results]
            logger.debug(f"Batch detected: {len(emotions)} emotions")
            return emotions
            
        except Exception as e:
            logger.error(f"❌ Batch emotion detection failed: {e}")
            return ["neutral"] * len(texts)
    
    def detect_batch_detailed(self, texts: List[str]) -> List[Dict[str, Any]]:
        """
        Detect emotions for multiple texts with details
        
        Args:
            texts: List of input texts
            
        Returns:
            List of dicts with emotion, confidence, and text
        
        Usage:
            results = emotion_service.detect_batch_detailed(["I'm happy", "I'm sad"])
            # Returns: [{"emotion": "joy", "confidence": 0.98, ...}, ...]
        """
        self._ensure_model_loaded()
        
        if not self.model:
            logger.error("❌ Emotion model not available")
            return [
                {
                    "success": False,
                    "emotion": "neutral",
                    "confidence": 0.0,
                    "text": text,
                    "error": "Model not available"
                }
                for text in texts
            ]
        
        try:
            results = self.model(texts)
            
            detailed_results = []
            for text, result in zip(texts, results):
                detailed_results.append({
                    "success": True,
                    "emotion": result["label"].lower(),
                    "confidence": round(result["score"], 4),
                    "text": text
                })
            
            logger.info(f"Batch processed: {len(detailed_results)} texts")
            return detailed_results
            
        except Exception as e:
            logger.error(f"❌ Batch emotion detection failed: {e}")
            return [
                {
                    "success": False,
                    "emotion": "neutral",
                    "confidence": 0.0,
                    "text": text,
                    "error": str(e)
                }
                for text in texts
            ]
    
    def get_status(self) -> Dict[str, Any]:
        """Get service status"""
        return {
            "available": self.model is not None,
            "device": DEVICE
        }


# Singleton instance
emotion_service = EmotionService()


# Convenience function (backward compatible)
async def detect_emotion(text: str) -> str:
    """
    Simple emotion detection (backward compatible with your old code)
    
    Usage in your routes:
        from app.services.emotion_service import detect_emotion
        emotion = await detect_emotion(user_message)
    """
    # Wrapped in async for backward compatibility
    # (emotion detection is fast, doesn't need true async)
    return emotion_service.detect(text)