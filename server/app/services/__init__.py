"""
Services Module - High-level business logic layer
Uses ML models as foundation, adds utilities and convenience methods
"""

from app.services.stt_services import (
    whisper_service,
    transcribe_audio,
    transcribe_audio_detailed,
)
from app.services.stt_session_manager import stt_session_manager
from app.services.emotion_services import (
    emotion_service,
    detect_emotion,
)
from app.services.embedding_services import (
    embedding_service,
    get_text_similarity,
    search_similar_texts,
)
from app.services.tts_services import tts_service
from app.services.chat import (
    StreamService,
    TaskSummarySpeechService,
    ToolOutputDeliveryService,
    chat,
    get_task_summary_speech_service,
    get_tool_output_delivery_service,
    parallel_chat_execution,
    process_sqh,
    stream_chat_response,
)

__all__ = [
    # Core services
    "whisper_service",
    "emotion_service",
    "embedding_service",
    "stt_session_manager",
    "tts_service",
    # Chat/task services
    "chat",
    "process_sqh",
    "StreamService",
    "stream_chat_response",
    "parallel_chat_execution",
    "TaskSummarySpeechService",
    "get_task_summary_speech_service",
    "ToolOutputDeliveryService",
    "get_tool_output_delivery_service",
    # Convenience helpers
    "transcribe_audio",
    "transcribe_audio_detailed",
    "detect_emotion",
    "get_text_similarity",
    "search_similar_texts",
]
