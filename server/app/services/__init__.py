"""
Services Module - High-level business logic layer
Uses ML models as foundation, adds utilities and convenience methods
"""
from app.services.stt_services import (
    whisper_service,
    transcribe_audio,
    transcribe_audio_detailed
)
from app.services.stt_session_manager import stt_session_manager
from app.services.emotion_services import (
    emotion_service,
    detect_emotion
)
from app.services.embedding_services import (
    embedding_service,
    get_text_similarity,
    search_similar_texts,
)

from app.services.tts_services import (
  tts_service,
)

__all__ = [
    # Services
    "whisper_service",
    "emotion_service",
    "embedding_service",
    "stt_session_manager",
    
    # Convenience functions (backward compatible)
    "transcribe_audio",
    "transcribe_audio_detailed",
    "detect_emotion",
    "get_text_similarity",
    "search_similar_texts",
]
