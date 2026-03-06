"""
Services module with lazy exports.

Avoids eager import side-effects (for example local ML model initialization)
at process import time.
"""

from importlib import import_module
from typing import Any

_EXPORTS: dict[str, tuple[str, str]] = {
    # STT
    "whisper_service": ("app.services.stt_services", "whisper_service"),
    "transcribe_audio": ("app.services.stt_services", "transcribe_audio"),
    "transcribe_audio_detailed": ("app.services.stt_services", "transcribe_audio_detailed"),
    "stt_session_manager": ("app.services.stt_session_manager", "stt_session_manager"),
    # Emotion
    "emotion_service": ("app.services.emotion_services", "emotion_service"),
    "detect_emotion": ("app.services.emotion_services", "detect_emotion"),
    # Embeddings
    "embedding_service": ("app.services.embedding_services", "embedding_service"),
    "get_text_similarity": ("app.services.embedding_services", "get_text_similarity"),
    "search_similar_texts": ("app.services.embedding_services", "search_similar_texts"),
    # TTS
    "tts_service": ("app.services.tts_services", "tts_service"),
    # Chat/task services
    "chat": ("app.services.chat", "chat"),
    "process_sqh": ("app.services.chat", "process_sqh"),
    "StreamService": ("app.services.chat", "StreamService"),
    "stream_chat_response": ("app.services.chat", "stream_chat_response"),
    "parallel_chat_execution": ("app.services.chat", "parallel_chat_execution"),
    "TaskSummarySpeechService": ("app.services.chat", "TaskSummarySpeechService"),
    "get_task_summary_speech_service": ("app.services.chat", "get_task_summary_speech_service"),
    "ToolOutputDeliveryService": ("app.services.chat", "ToolOutputDeliveryService"),
    "get_tool_output_delivery_service": ("app.services.chat", "get_tool_output_delivery_service"),
}

__all__ = list(_EXPORTS.keys())


def __getattr__(name: str) -> Any:
    try:
        module_path, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    module = import_module(module_path)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
