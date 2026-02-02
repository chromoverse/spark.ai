"""
Whisper Service - Speech-to-Text with auto GPU/CPU optimization
Single source of truth for all STT operations
"""
import base64
import logging
import tempfile
import os
import time
from typing import Optional, Dict, Any

from app.ml import model_loader,DEVICE
from app.utils.async_utils import make_async

logger = logging.getLogger(__name__)

# Audio format configuration
ALLOWED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".mpga", ".webm", ".mp4", ".ogg"}
MIME_TO_EXT = {
    "audio/webm": ".webm",
    "audio/webm;codecs=opus": ".webm",
    "audio/wav": ".wav",
    "audio/mp3": ".mp3",
    "audio/mpeg": ".mp3",
    "audio/m4a": ".m4a",
    "audio/mp4": ".mp4",
    "audio/ogg": ".ogg",
}

class WhisperService:
    """Unified Whisper service using ML model loader"""
    
    def __init__(self):
        self.model = None
        self._ensure_model_loaded()
    
    def _ensure_model_loaded(self):
        """Ensure Whisper model is loaded"""
        if self.model is None:
            self.model = model_loader.get_model("whisper")
            if self.model is None:
                logger.warning("⚠️ Whisper model not loaded, attempting to load...")
                self.model = model_loader.load_model("whisper")
            
            if self.model:
                device = DEVICE
                speed = "70-150ms" if device == "cuda" else "1.5-3s"
                logger.info(f"✅ Whisper service ready on {device.upper()} (expected: {speed})")
    
    def _decode_audio(self, audio_data: Any) -> bytes:
        """Decode audio data from base64 or bytes"""
        if isinstance(audio_data, str):
            audio_bytes = base64.b64decode(audio_data)
            logger.debug(f"✅ Decoded base64 to {len(audio_bytes)} bytes")
        else:
            audio_bytes = audio_data
        
        if len(audio_bytes) < 1000:
            logger.warning(f"⚠️ Audio too small: {len(audio_bytes)} bytes")
            raise ValueError("Audio data too small (< 1KB)")
        
        return audio_bytes
    
    def _get_extension(self, mime_type: str) -> str:
        """Get file extension from MIME type"""
        base_mime = mime_type.split(";")[0].strip()
        ext = MIME_TO_EXT.get(base_mime, ".webm")
        
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"Unsupported audio type: {mime_type}")
        
        return ext
    
    def _transcribe_sync(
        self,
        audio_data: Any,
        mime_type: str = "audio/webm",
        language: Optional[str] = "en",
        task: str = "transcribe",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Synchronous transcription with detailed results
        
        Args:
            audio_data: Base64 string or bytes
            mime_type: Audio MIME type
            language: Language code (None for auto-detect)
            task: "transcribe" or "translate"
            **kwargs: Additional Whisper parameters
        
        Returns:
            Dict with text, segments, language, duration, etc.
        """
        self._ensure_model_loaded()
        
        if not self.model:
            raise RuntimeError("Whisper model not available")
        
        tmp_path = None
        try:
            # Decode and validate audio
            audio_bytes = self._decode_audio(audio_data)
            ext = self._get_extension(mime_type)
            
            # Write to temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name
            
            logger.info(f"📝 Processing {len(audio_bytes)} bytes ({ext})")
            
            # Transcribe with optimized settings
            start_time = time.time()
            
            # Merge user kwargs with defaults
            transcribe_params = {
                "language": language,
                "task": task,
                "beam_size": kwargs.get("beam_size", 1),
                "best_of": kwargs.get("best_of", 1),
                "vad_filter": kwargs.get("vad_filter", True),
                "vad_parameters": kwargs.get("vad_parameters", {
                    "threshold": 0.3,
                    "min_speech_duration_ms": 250,
                    "min_silence_duration_ms": 300,
                }),
                "temperature": kwargs.get("temperature", 0.0),
                "no_speech_threshold": kwargs.get("no_speech_threshold", 0.6),
                "condition_on_previous_text": kwargs.get("condition_on_previous_text", False),
                "initial_prompt": kwargs.get("initial_prompt", 
                    "Commands: Spotify, WhatsApp, YouTube, notepad, Google, kholo, chalao, bajao, likho, bhejo, search"
                ),
            }
            
            segments, info = self.model.transcribe(tmp_path, **transcribe_params)
            
            # Extract segments
            text_segments = []
            segment_details = []
            
            for segment in segments:
                if segment.text.strip():
                    text_segments.append(segment.text.strip())
                    segment_details.append({
                        "start": round(segment.start, 2),
                        "end": round(segment.end, 2),
                        "text": segment.text.strip()
                    })
            
            full_text = " ".join(text_segments).strip()
            elapsed = time.time() - start_time
            
            logger.info(f"✅ Transcribed: '{full_text}' ({elapsed:.2f}s)")
            
            if not full_text or len(full_text) < 2:
                logger.warning("⚠️ No speech detected")
                return {
                    "success": False,
                    "text": "",
                    "message": "No speech detected",
                    "duration": elapsed
                }
            
            return {
                "success": True,
                "text": full_text,
                "segments": segment_details,
                "language": info.language,
                "language_probability": round(info.language_probability, 4),
                "duration": round(info.duration, 2),
                "processing_time": round(elapsed, 2)
            }
            
        except Exception as e:
            logger.error(f"❌ Transcription failed: {e}", exc_info=True)
            return {
                "success": False,
                "text": "",
                "error": str(e)
            }
        
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception as e:
                    logger.warning(f"⚠️ Cleanup failed: {e}")
    
    @make_async
    def transcribe(
        self,
        audio_data: Any,
        mime_type: str = "audio/webm",
        language: Optional[str] = "en",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Async transcription - main public API
        
        Usage:
            result = await whisper_service.transcribe(audio_data)
            print(result["text"])
        """
        return self._transcribe_sync(audio_data, mime_type, language, **kwargs)
    
    @make_async
    def transcribe_simple(
        self,
        audio_data: Any,
        mime_type: str = "audio/webm"
    ) -> str:
        """
        Simple async transcription - returns only text
        
        Usage:
            text = await whisper_service.transcribe_simple(audio_data)
        """
        result = self._transcribe_sync(audio_data, mime_type)
        return result.get("text", "[Transcription failed]")
    
    @make_async
    def detect_language(
        self,
        audio_data: Any,
        mime_type: str = "audio/webm"
    ) -> Dict[str, Any]:
        """
        Detect language from audio
        
        Usage:
            result = await whisper_service.detect_language(audio_data)
            print(result["language"])
        """
        result = self._transcribe_sync(audio_data, mime_type, language=None)
        
        if result.get("success"):
            return {
                "success": True,
                "language": result["language"],
                "confidence": result["language_probability"],
                "sample_text": result["text"][:100]
            }
        else:
            return result
    
    def get_status(self) -> Dict[str, Any]:
        """Get service status"""
        return {
            "available": self.model is not None,
            "device": DEVICE,
            "expected_speed": "70-150ms" if DEVICE == "cuda" else "1.5-3s"
        }


# Singleton instance
whisper_service = WhisperService()


# Convenience functions (backward compatible with your old code)
async def transcribe_audio(audio_data: Any, mime_type: str = "audio/webm") -> str:
    """
    Simple transcription - returns only text (backward compatible)
    
    Usage in your routes:
        from app.services.whisper_service import transcribe_audio
        text = await transcribe_audio(audio_data)
    """
    return await whisper_service.transcribe_simple(audio_data, mime_type)


async def transcribe_audio_detailed(
    audio_data: Any,
    mime_type: str = "audio/webm",
    language: Optional[str] = "en"
) -> Dict[str, Any]:
    """
    Detailed transcription - returns full result dict
    
    Usage:
        result = await transcribe_audio_detailed(audio_data)
        print(result["text"], result["segments"])
    """
    return await whisper_service.transcribe(audio_data, mime_type, language)