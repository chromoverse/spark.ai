from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional, Dict, Any

class TTSEngine(ABC):
    """Abstract base class for TTS engines"""
    
    @abstractmethod
    def get_engine_name(self) -> str:
        """Return the name of the engine"""
        pass
        
    @abstractmethod
    async def generate_stream(
        self, 
        text: str, 
        voice: str, 
        speed: float, 
        lang: str
    ) -> AsyncGenerator[bytes, None]:
        """
        Generate audio stream (WAV format preference)
        
        Args:
            text: Text to synthesize
            voice: Voice ID/name
            speed: Speech speed
            lang: Language code
            
        Yields:
            Audio chunks
        """
        yield b""  # abstract async generator stub
        
    @abstractmethod
    async def is_available(self) -> bool:
        """Check if engine is available/healthy"""
        pass
