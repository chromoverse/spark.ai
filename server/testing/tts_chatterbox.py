"""Chatterbox TTS Service with Auto Device Detection & Emotion Support"""
import torch
import numpy as np
from typing import Optional, Iterator
import logging
from io import BytesIO
import wave

logger = logging.getLogger(__name__)


class ChatterboxTTSService:
    def __init__(self):
        self.model = None
        self.device = self._detect_device()
        self._initialize_model()

    def _detect_device(self) -> str:
        """Auto-detect best available device"""
        if torch.cuda.is_available():
            device = "cuda"
            gpu_name = torch.cuda.get_device_name(0)
            logger.info(f"🎮 Using NVIDIA GPU: {gpu_name}")
        elif hasattr(torch.version, 'hip') and torch.version.hip is not None:
            device = "cuda"  # ROCm uses cuda backend
            logger.info(f"🎮 Using AMD GPU (ROCm)")
        else:
            device = "cpu"
            logger.info("💻 Using CPU (slower, consider GPU for production)")
        
        return device

    def _initialize_model(self):
        """Initialize Chatterbox model"""
        try:
            from chatterbox import ChatterboxTTS
            
            logger.info(f"📦 Loading Chatterbox multilingual model on {self.device}...")
            
            # Load multilingual model
            self.model = ChatterboxTTS.from_pretrained(
                "resemble-ai/chatterbox-multilingual-turbo",
                device=self.device
            )
            
            logger.info("✅ Chatterbox model loaded successfully!")
            
        except Exception as e:
            logger.error(f"❌ Failed to load Chatterbox model: {e}")
            raise

    def _create_wav_chunk(self, audio_data: np.ndarray, sample_rate: int = 24000) -> bytes:
        """Convert audio numpy array to WAV bytes"""
        buffer = BytesIO()
        
        with wave.open(buffer, 'wb') as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(sample_rate)
            
            # Convert float to int16
            audio_int16 = (audio_data * 32767).astype(np.int16)
            wav_file.writeframes(audio_int16.tobytes())
        
        return buffer.getvalue()

    def generate_stream(
        self, 
        text: str, 
        exaggeration: float = 0.5,
        language: str = "auto"
    ) -> Iterator[bytes]:
        """
        Generate TTS audio in streaming chunks
        
        Args:
            text: Text with emotion tags like [laugh], [chuckle], [sigh]
            exaggeration: Emotion intensity (0.0 = monotone, 2.0 = dramatic)
            language: Language code or "auto" for auto-detection
        
        Yields:
            WAV audio chunks as bytes
        """
        if not self.model:
            logger.error("Model not initialized")
            return

        try:
            logger.info(f"🎤 Generating TTS: '{text[:50]}...' (exaggeration={exaggeration})")
            
            # Generate audio
            # Note: Chatterbox Turbo supports emotion tags natively
            audio = self.model.generate(
                text=text,
                exaggeration=exaggeration,
                language=language if language != "auto" else None
            )
            
            # Convert to numpy if it's a tensor
            if isinstance(audio, torch.Tensor):
                audio = audio.cpu().numpy()
            
            # Chunk the audio for streaming (split into 0.5s chunks)
            sample_rate = 24000
            chunk_size = sample_rate // 2  # 0.5 second chunks
            
            total_samples = len(audio)
            for i in range(0, total_samples, chunk_size):
                chunk = audio[i:i + chunk_size]
                wav_bytes = self._create_wav_chunk(chunk, sample_rate)
                yield wav_bytes
            
            logger.info(f"✅ TTS generation complete ({total_samples / sample_rate:.2f}s audio)")
            
        except Exception as e:
            logger.error(f"❌ TTS generation failed: {e}")
            raise

    def generate(
        self, 
        text: str, 
        exaggeration: float = 0.5,
        language: str = "auto"
    ) -> bytes:
        """Generate complete audio file (non-streaming)"""
        chunks = list(self.generate_stream(text, exaggeration, language))
        if chunks:
            return chunks[0]  # Return first chunk (full audio)
        return b""


# Singleton instance
_tts_service: Optional[ChatterboxTTSService] = None

def get_tts_service() -> ChatterboxTTSService:
    """Get or create singleton TTS service"""
    global _tts_service
    if _tts_service is None:
        _tts_service = ChatterboxTTSService()
    return _tts_service