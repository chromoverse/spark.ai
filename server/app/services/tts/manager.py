import logging
import asyncio
from typing import AsyncGenerator, List, Optional, cast, AsyncIterator
from app.services.tts.base import TTSEngine
from app.services.tts.kokoro_engine import KokoroEngine
from app.services.tts.edge_engine import EdgeEngine
from app.services.tts.gtts_engine import GTTSEngine
from app.services.tts.voice_selector import VoiceSelector
from app.config import settings

logger = logging.getLogger(__name__)

class TTSManager:
    """
    Manages TTS engines with fallback priority.

    Priority order:
        0. Groq TTS (when cloud mode is enabled)
        1. Edge TTS
        2. Kokoro (local mode + desktop only — skipped in cloud mode)
        3. gTTS
    """
    
    def __init__(self):
        self.engines: List[TTSEngine] = []
        self._initialized = False
        
    async def initialize(self):
        """Initialize all engines"""
        if self._initialized:
            return

        # Priority 0 — Groq (only when cloud mode is enabled)
        if settings.is_cloud_mode:
            try:
                from app.services.tts.groq_engine import GroqEngine
                groq = GroqEngine()
                if await groq.is_available():
                    self.engines.append(groq)
                    logger.info("✅ TTS: Groq engine enabled (priority 0)")
            except Exception as e:
                logger.warning(f"⚠️ TTS: Groq engine unavailable: {e}")
            
        # Priority 1: Edge TTS
        edge = EdgeEngine()
        if await edge.is_available():
            self.engines.append(edge)
            logger.info("✅ TTS: Edge engine enabled")

        # Priority 2: Kokoro (local mode + desktop only)
        # Skipped in cloud mode — Groq + Edge + gTTS form a 3-tier remote chain.
        if settings.is_local_mode and settings.environment == "DESKTOP":
            kokoro = KokoroEngine()
            if await kokoro.is_available():
                self.engines.append(kokoro)
                logger.info("✅ TTS: Kokoro engine enabled")
        else:
            logger.info(
                "⏭️ TTS: skipping Kokoro init (mode=%s, env=%s)",
                settings.inference_mode,
                settings.environment,
            )

        # Priority 3: gTTS
        gtts = GTTSEngine()
        if await gtts.is_available():
            self.engines.append(gtts)
            logger.info("✅ TTS: gTTS engine enabled")
            
        self._initialized = True
        
    async def generate_stream(
        self, 
        text: str, 
        voice: Optional[str] = None, 
        speed: float = 1.0, 
        lang: Optional[str] = None,
        gender: Optional[str] = None,
        prefer_low_latency: bool = False,
    ) -> AsyncGenerator[bytes, None]:
        """
        Generate audio using the first working engine
        """
        if not self._initialized:
            await self.initialize()
            
        # Auto-detect language if not provided
        if not lang:
            lang = VoiceSelector.detect_language(text)
            
        # Select best voice if not provided
        if not voice:
            # Note: VoiceSelector returns Kokoro-compatible voice IDs mostly
            voice = VoiceSelector.get_voice(lang, gender)
            
        last_error = None
        engines = self._engine_order(prefer_low_latency=prefer_low_latency)
        if prefer_low_latency:
            logger.debug("⚡ TTS low-latency engine order: %s", [engine.get_engine_name() for engine in engines])

        # Per-engine retry policy:
        # • Up to 3 attempts per engine before moving on to the next.
        # • If chunks have already been yielded to the caller, do NOT retry —
        #   that would replay audio mid-stream. Move to the next engine.
        # • Exponential backoff: 100ms, 200ms.
        per_engine_attempts = 3
        for engine in engines:
            engine_name = engine.get_engine_name()

            for attempt in range(1, per_engine_attempts + 1):
                chunks_yielded = False
                try:
                    logger.debug(
                        "🔄 TTS %s attempt %d/%d…",
                        engine_name, attempt, per_engine_attempts,
                    )
                    async for chunk in engine.generate_stream(text, voice, speed, lang):
                        chunks_yielded = True
                        yield chunk
                    return  # success — entire stream completed

                except Exception as e:
                    last_error = e
                    if chunks_yielded:
                        logger.warning(
                            "⚠️ TTS %s failed mid-stream after yielding chunks: %s — moving to next engine",
                            engine_name, e,
                        )
                        break  # cannot safely retry — try the next engine

                    if attempt >= per_engine_attempts:
                        logger.warning(
                            "⚠️ TTS %s failed all %d attempts: %s",
                            engine_name, per_engine_attempts, e,
                        )
                        break  # exhaust this engine, move to next

                    delay = 0.1 * (2 ** (attempt - 1))
                    logger.warning(
                        "⚠️ TTS %s attempt %d/%d failed (%s); retrying in %.0fms",
                        engine_name, attempt, per_engine_attempts, e, delay * 1000,
                    )
                    await asyncio.sleep(delay)

        # If we get here, all engines failed
        logger.error("❌ All TTS engines failed")
        if last_error:
            raise last_error
        else:
            raise RuntimeError("No TTS engines available")

    def _engine_order(self, prefer_low_latency: bool) -> List[TTSEngine]:
        # Keep a single deterministic fallback order for all modes:
        # Groq -> Edge -> Kokoro -> gTTS.
        return list(self.engines)
            
    # Singleton access
    @classmethod
    def get_instance(cls):
        if not hasattr(cls, "_instance"):
            cls._instance = cls()
        return cls._instance

# Global instance
tts_manager = TTSManager()
