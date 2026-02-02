import asyncio
import logging
from typing import AsyncGenerator, Optional, Dict, Any, Literal, Tuple, List
from io import BytesIO
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import OrderedDict
import hashlib
import random
from functools import lru_cache
from threading import Lock
import struct
import wave

logger = logging.getLogger(__name__)

# Type aliases for clarity
VoiceID = str
LanguageCode = str
GenderType = Literal["male", "female"]
AudioBytes = bytes


def pcm_to_wav(pcm_data: bytes, sample_rate: int = 24000, channels: int = 1) -> bytes:
    """
    Convert raw PCM audio to WAV format
    
    Args:
        pcm_data: Raw PCM audio bytes (int16)
        sample_rate: Sample rate in Hz (Kokoro uses 24000)
        channels: Number of audio channels (1 for mono)
    
    Returns:
        Complete WAV file as bytes
    """
    buffer = BytesIO()
    
    with wave.open(buffer, 'wb') as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)  # 2 bytes for int16
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
    
    buffer.seek(0)
    return buffer.read()


@dataclass
class CacheEntry:
    """Cache entry with metadata"""
    audio_data: AudioBytes
    created_at: datetime
    access_count: int = 0
    last_accessed: datetime = field(default_factory=datetime.now)
    language: str = ""
    voice: str = ""
    
    def touch(self) -> None:
        """Update access metadata"""
        self.access_count += 1
        self.last_accessed = datetime.now()


class LanguageCache:
    """Language-aware LRU cache with size limits and TTL"""
    
    def __init__(self, max_size_per_lang: int = 50, ttl_seconds: int = 3600):
        self.max_size_per_lang = max_size_per_lang
        self.ttl = timedelta(seconds=ttl_seconds)
        self._caches: Dict[str, OrderedDict[str, CacheEntry]] = {}
        self._lock = Lock()
        self._hits = 0
        self._misses = 0
        self._hits_by_lang: Dict[str, int] = {}
        self._misses_by_lang: Dict[str, int] = {}
    
    def _get_or_create_lang_cache(self, lang: str) -> OrderedDict[str, CacheEntry]:
        """Get or create cache for a specific language"""
        if lang not in self._caches:
            self._caches[lang] = OrderedDict()
            self._hits_by_lang[lang] = 0
            self._misses_by_lang[lang] = 0
            logger.info(f"🆕 Created cache for language: {lang}")
        return self._caches[lang]
    
    def _is_expired(self, entry: CacheEntry) -> bool:
        """Check if cache entry is expired"""
        return datetime.now() - entry.created_at > self.ttl
    
    def _evict_expired(self, lang: str) -> int:
        """Remove expired entries for a language"""
        cache = self._caches.get(lang)
        if not cache:
            return 0
        
        now = datetime.now()
        expired_keys = [
            k for k, v in cache.items() 
            if now - v.created_at > self.ttl
        ]
        for key in expired_keys:
            del cache[key]
        
        if expired_keys:
            logger.debug(f"🗑️ Evicted {len(expired_keys)} expired entries for {lang}")
        
        return len(expired_keys)
    
    def get(self, key: str, lang: str, voice: str) -> Optional[AudioBytes]:
        """Thread-safe cache retrieval"""
        with self._lock:
            cache = self._caches.get(lang)
            if not cache or key not in cache:
                self._misses += 1
                self._misses_by_lang[lang] = self._misses_by_lang.get(lang, 0) + 1
                logger.debug(f"❌ Cache MISS: lang={lang}, voice={voice}")
                return None
            
            entry = cache[key]
            
            # Check expiration
            if self._is_expired(entry):
                del cache[key]
                self._misses += 1
                self._misses_by_lang[lang] = self._misses_by_lang.get(lang, 0) + 1
                logger.debug(f"⏰ Cache EXPIRED: lang={lang}, voice={voice}")
                return None
            
            # Move to end (most recently used)
            cache.move_to_end(key)
            entry.touch()
            self._hits += 1
            self._hits_by_lang[lang] = self._hits_by_lang.get(lang, 0) + 1
            
            logger.info(f"⚡ Cache HIT: lang={lang}, voice={voice}, size={len(entry.audio_data):,} bytes")
            return entry.audio_data
    
    def put(self, key: str, data: AudioBytes, lang: str, voice: str) -> None:
        """Thread-safe cache insertion"""
        with self._lock:
            cache = self._get_or_create_lang_cache(lang)
            
            # Evict expired entries first
            self._evict_expired(lang)
            
            # If key exists, update it
            if key in cache:
                cache[key].audio_data = data
                cache[key].created_at = datetime.now()
                cache.move_to_end(key)
                logger.debug(f"🔄 Cache UPDATE: lang={lang}, voice={voice}")
                return
            
            # Evict oldest if at capacity for this language
            if len(cache) >= self.max_size_per_lang:
                evicted_key, evicted_entry = cache.popitem(last=False)
                logger.debug(f"🗑️ Evicted LRU: lang={lang}, key={evicted_key[:16]}...")
            
            # Add new entry
            cache[key] = CacheEntry(
                audio_data=data,
                created_at=datetime.now(),
                language=lang,
                voice=voice
            )
            logger.info(f"💾 Cache STORE: lang={lang}, voice={voice}, size={len(data):,} bytes")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total * 100) if total > 0 else 0
            
            lang_stats = {}
            total_entries = 0
            for lang, cache in self._caches.items():
                lang_total = self._hits_by_lang.get(lang, 0) + self._misses_by_lang.get(lang, 0)
                lang_hit_rate = (self._hits_by_lang.get(lang, 0) / lang_total * 100) if lang_total > 0 else 0
                lang_stats[lang] = {
                    "entries": len(cache),
                    "hits": self._hits_by_lang.get(lang, 0),
                    "misses": self._misses_by_lang.get(lang, 0),
                    "hit_rate": f"{lang_hit_rate:.2f}%"
                }
                total_entries += len(cache)
            
            return {
                "total_entries": total_entries,
                "languages": len(self._caches),
                "global_hits": self._hits,
                "global_misses": self._misses,
                "global_hit_rate": f"{hit_rate:.2f}%",
                "by_language": lang_stats
            }
    
    def clear(self, lang: Optional[str] = None) -> None:
        """Clear all cache entries or specific language"""
        with self._lock:
            if lang:
                if lang in self._caches:
                    self._caches[lang].clear()
                    logger.info(f"🗑️ Cleared cache for language: {lang}")
            else:
                self._caches.clear()
                self._hits = 0
                self._misses = 0
                self._hits_by_lang.clear()
                self._misses_by_lang.clear()
                logger.info("🗑️ Cleared all language caches")


class VoiceSelector:
    """
    Intelligent voice selector - automatically picks the best voice
    based on language and gender
    """
    
    # Language mappings with best voices (ordered by quality)
    VOICE_MAP: Dict[str, Dict[str, Any]] = {
        # Hindi
        "hi": {
            "female": ["hf_alpha", "hf_beta"],
            "male": ["hm_omega", "hm_psi"],
            "default_gender": "female"
        },
        "hindi": {
            "female": ["hf_alpha", "hf_beta"],
            "male": ["hm_omega", "hm_psi"],
            "default_gender": "female"
        },
        
        # English (American)
        "en": {
            "female": ["af_heart", "af_bella", "af_nicole", "af_sarah"],
            "male": ["am_michael", "am_fenrir", "am_puck"],
            "default_gender": "female"
        },
        "en-us": {
            "female": ["af_heart", "af_bella", "af_nicole"],
            "male": ["am_michael", "am_fenrir"],
            "default_gender": "female"
        },
        "english": {
            "female": ["af_heart", "af_bella", "af_nicole"],
            "male": ["am_michael", "am_fenrir"],
            "default_gender": "female"
        },
        
        # English (British)
        "en-gb": {
            "female": ["bf_emma", "bf_isabella"],
            "male": ["bm_fable", "bm_george"],
            "default_gender": "female"
        },
        
        # Japanese
        "ja": {
            "female": ["jf_alpha", "jf_gongitsune"],
            "male": ["jm_kumo"],
            "default_gender": "female"
        },
        "japanese": {
            "female": ["jf_alpha", "jf_gongitsune"],
            "male": ["jm_kumo"],
            "default_gender": "female"
        },
        
        # Mandarin Chinese
        "zh": {
            "female": ["zf_xiaobei", "zf_xiaoni"],
            "male": ["zm_yunjian", "zm_yunxi"],
            "default_gender": "female"
        },
        "chinese": {
            "female": ["zf_xiaobei", "zf_xiaoni"],
            "male": ["zm_yunjian", "zm_yunxi"],
            "default_gender": "female"
        },
        
        # Spanish
        "es": {
            "female": ["ef_dora"],
            "male": ["em_alex", "em_santa"],
            "default_gender": "female"
        },
        "spanish": {
            "female": ["ef_dora"],
            "male": ["em_alex"],
            "default_gender": "female"
        },
        
        # French
        "fr": {
            "female": ["ff_siwis"],
            "male": [],
            "default_gender": "female"
        },
        "french": {
            "female": ["ff_siwis"],
            "male": [],
            "default_gender": "female"
        },
        
        # Italian
        "it": {
            "female": ["if_sara"],
            "male": ["im_nicola"],
            "default_gender": "female"
        },
        "italian": {
            "female": ["if_sara"],
            "male": ["im_nicola"],
            "default_gender": "female"
        },
        
        # Portuguese (Brazilian)
        "pt": {
            "female": ["pf_dora"],
            "male": ["pm_alex", "pm_santa"],
            "default_gender": "female"
        },
        "pt-br": {
            "female": ["pf_dora"],
            "male": ["pm_alex"],
            "default_gender": "female"
        },
        "portuguese": {
            "female": ["pf_dora"],
            "male": ["pm_alex"],
            "default_gender": "female"
        },
    }
    
    # Kokoro language codes
    KOKORO_LANG_CODES: Dict[str, str] = {
        "hi": "h", "hindi": "h",
        "en": "a", "en-us": "a", "english": "a",
        "en-gb": "b",
        "ja": "j", "japanese": "j",
        "zh": "z", "chinese": "z",
        "es": "e", "spanish": "e",
        "fr": "f", "french": "f",
        "it": "i", "italian": "i",
        "pt": "p", "pt-br": "p", "portuguese": "p",
    }
    
    # Edge TTS fallback voices
    EDGE_FALLBACK: Dict[str, Dict[str, str]] = {
        "hi": {
            "female": "hi-IN-SwaraNeural",
            "male": "hi-IN-MadhurNeural"
        },
        "en": {
            "female": "en-US-AriaNeural",
            "male": "en-US-GuyNeural"
        },
        "en-gb": {
            "female": "en-GB-SoniaNeural",
            "male": "en-GB-RyanNeural"
        },
    }
    
    # gTTS language codes
    GTTS_LANG_CODES: Dict[str, str] = {
        "hi": "hi", "hindi": "hi",
        "en": "en", "en-us": "en", "en-gb": "en", "english": "en",
        "ja": "ja", "japanese": "ja",
        "zh": "zh-CN", "chinese": "zh-CN",
        "es": "es", "spanish": "es",
        "fr": "fr", "french": "fr",
        "it": "it", "italian": "it",
        "pt": "pt", "pt-br": "pt", "portuguese": "pt",
    }
    
    @classmethod
    def get_voice(
        cls, 
        lang: str, 
        gender: Optional[str] = None,
        randomize: bool = False
    ) -> VoiceID:
        """
        Automatically select the best voice based on language and gender
        
        Args:
            lang: Language code (e.g., 'hi', 'en', 'hindi', 'english')
            gender: 'male', 'female', or None (uses default)
            randomize: If True, randomly picks from available voices
        
        Returns:
            Voice ID for Kokoro
        """
        # Normalize language
        lang = lang.lower().strip()
        
        # Get language config
        lang_config = cls.VOICE_MAP.get(lang)
        if not lang_config:
            logger.warning(f"⚠️ Language '{lang}' not found, defaulting to English")
            lang_config = cls.VOICE_MAP["en"]
        
        # Determine gender
        if not gender:
            gender = lang_config["default_gender"]
        else:
            gender = gender.lower().strip()
        
        # Get voice list for gender
        voices: List[str] = lang_config.get(gender, [])
        
        # If no voices for this gender, try opposite gender
        if not voices:
            opposite_gender: str = "male" if gender == "female" else "female"
            voices = lang_config.get(opposite_gender, [])
            if voices:
                logger.info(f"ℹ️ No {gender} voice for {lang}, using {opposite_gender}")
        
        # If still no voices, use default
        if not voices:
            logger.warning(f"⚠️ No voices found for {lang}, using default")
            return "af_heart"
        
        # Select voice
        if randomize:
            voice = random.choice(voices)
            logger.debug(f"🎲 Randomly selected voice: {voice}")
        else:
            voice = voices[0]  # Use best quality (first in list)
        
        return voice
    
    @classmethod
    @lru_cache(maxsize=128)
    def get_kokoro_lang_code(cls, lang: str) -> str:
        """Get Kokoro language code (cached)"""
        return cls.KOKORO_LANG_CODES.get(lang.lower(), "a")
    
    @classmethod
    def get_edge_voice(cls, lang: str, gender: str) -> Optional[str]:
        """Get Edge TTS fallback voice"""
        lang_voices = cls.EDGE_FALLBACK.get(lang.lower())
        if lang_voices:
            return lang_voices.get(gender.lower(), lang_voices.get("female"))
        return None
    
    @classmethod
    @lru_cache(maxsize=128)
    def get_gtts_lang(cls, lang: str) -> str:
        """Get gTTS language code (cached)"""
        return cls.GTTS_LANG_CODES.get(lang.lower(), "en")
    
    @classmethod
    @lru_cache(maxsize=1000)
    def detect_language(cls, text: str) -> str:
        """
        Simple language detection based on character set (cached)
        """
        # Check for Devanagari (Hindi)
        if any('\u0900' <= char <= '\u097F' for char in text):
            return "hi"
        
        # Check for Chinese
        if any('\u4e00' <= char <= '\u9fff' for char in text):
            return "zh"
        
        # Check for Japanese
        if any('\u3040' <= char <= '\u309f' or '\u30a0' <= char <= '\u30ff' for char in text):
            return "ja"
        
        # Default to English
        return "en"


class TTSService:
    """
    High-performance TTS service with language-based caching
    Thread-safe, async-optimized, and production-ready
    
    ✅ NOW OUTPUTS WAV FORMAT COMPATIBLE WITH BROWSERS
    """
    
    def __init__(
        self, 
        cache_size_per_lang: int = 50,
        cache_ttl: int = 3600,
        max_consecutive_failures: int = 3
    ):
        """
        Initialize TTS service
        
        Args:
            cache_size_per_lang: Maximum cached entries per language
            cache_ttl: Cache time-to-live in seconds
            max_consecutive_failures: Max failures before switching provider
        """
        # Pipeline management
        self.kokoro_pipeline: Dict[str, Any] = {}
        self.kokoro_initialized = False
        self.kokoro_available = False
        self._init_lock = asyncio.Lock()
        
        # Failure tracking
        self.consecutive_failures = 0
        self.max_consecutive_failures = max_consecutive_failures
        
        # Language-based caching system
        self.language_cache = LanguageCache(
            max_size_per_lang=cache_size_per_lang,
            ttl_seconds=cache_ttl
        )
        
        logger.info(f"🚀 TTS Service initialized (cache_per_lang={cache_size_per_lang}, ttl={cache_ttl}s)")
        
        # Background initialization
        asyncio.create_task(self._initialize_kokoro())
    
    def _get_cache_key(
        self, 
        text: str, 
        voice: VoiceID, 
        speed: float
    ) -> str:
        """Generate cache key for audio"""
        # Create deterministic hash
        key_string = f"{text}|{voice}|{speed:.2f}"
        return hashlib.md5(key_string.encode()).hexdigest()
    
    async def _initialize_kokoro(self) -> None:
        """Initialize Kokoro TTS pipeline lazily (thread-safe)"""
        async with self._init_lock:
            if self.kokoro_initialized:
                return
            
            try:
                from kokoro import KPipeline
                
                # Pre-load American English for snappy first response
                logger.info("🔄 Initializing Kokoro TTS...")
                self.kokoro_pipeline["a"] = KPipeline(lang_code="a")
                self.kokoro_available = True
                self.kokoro_initialized = True
                logger.info("✅ Kokoro initialized successfully (English ready)")
                
            except ImportError:
                logger.warning("⚠️ Kokoro not installed. Install: pip install kokoro")
                self.kokoro_available = False
                self.kokoro_initialized = True
            except Exception as e:
                logger.error(f"❌ Kokoro initialization failed: {e}")
                self.kokoro_available = False
                self.kokoro_initialized = True
    
    async def _get_kokoro_pipeline(self, lang_code: str) -> Any:
        """Get or create Kokoro pipeline for language (lazy-loaded)"""
        await self._initialize_kokoro()
        
        if not self.kokoro_available:
            raise RuntimeError("Kokoro is not available")
        
        if lang_code not in self.kokoro_pipeline:
            async with self._init_lock:
                # Double-check after acquiring lock
                if lang_code not in self.kokoro_pipeline:
                    from kokoro import KPipeline
                    logger.info(f"🔄 Loading Kokoro pipeline for lang_code='{lang_code}'...")
                    self.kokoro_pipeline[lang_code] = KPipeline(lang_code=lang_code)
                    logger.info(f"✅ Kokoro pipeline ready: lang_code='{lang_code}'")
        
        return self.kokoro_pipeline[lang_code]
    
    def _convert_to_bytes(self, audio_data: Any) -> AudioBytes:
        """
        Convert audio data to bytes (handles both NumPy arrays and PyTorch tensors)
        
        Args:
            audio_data: Audio as numpy array or PyTorch tensor
            
        Returns:
            Audio as bytes
        """
        try:
            # Check if it's a PyTorch tensor
            if hasattr(audio_data, 'cpu') and hasattr(audio_data, 'numpy'):
                # PyTorch tensor - convert to numpy first
                logger.debug("🔄 Converting PyTorch tensor to bytes")
                audio_array = audio_data.cpu().numpy()
            else:
                # Already numpy array
                audio_array = audio_data
            
            # Import numpy here to avoid issues if not installed
            import numpy as np
            
            # Convert to int16 if needed
            if audio_array.dtype in [np.float32, np.float64]:
                audio_int16 = (audio_array * 32767).astype(np.int16)
            else:
                audio_int16 = audio_array.astype(np.int16)
            
            return audio_int16.tobytes()
            
        except Exception as e:
            logger.error(f"❌ Audio conversion failed: {e}")
            raise
    
    async def _generate_kokoro_chunks(
        self,
        text: str,
        voice: VoiceID,
        lang_code: str,
        speed: float = 1.0,
        max_retries: int = 2,
        output_format: str = "wav"  # ✅ NEW PARAMETER
    ) -> AsyncGenerator[AudioBytes, None]:
        """
        Generate audio chunks using Kokoro TTS
        
        ✅ NOW CONVERTS TO WAV FORMAT FOR BROWSER COMPATIBILITY
        """
        
        last_error: Optional[Exception] = None
        
        for attempt in range(max_retries):
            try:
                pipeline = await self._get_kokoro_pipeline(lang_code)
                
                logger.info(f"🎤 Kokoro generating: lang={lang_code}, voice={voice}, speed={speed}")
                
                # Generate audio (this is CPU-bound, run in executor)
                def generate():
                    result = list(pipeline(text, voice=voice, speed=speed))
                    logger.debug(f"🔄 Kokoro generated {len(result)} segments")
                    return result
                
                generator = await asyncio.get_event_loop().run_in_executor(
                    None, generate
                )
                
                # ✅ COLLECT ALL PCM DATA FIRST
                all_pcm_chunks = []
                for graphemes, phonemes, audio_data in generator:
                    pcm_bytes = self._convert_to_bytes(audio_data)
                    all_pcm_chunks.append(pcm_bytes)
                
                # ✅ COMBINE AND CONVERT TO WAV
                if output_format == "wav":
                    combined_pcm = b"".join(all_pcm_chunks)
                    wav_data = pcm_to_wav(combined_pcm, sample_rate=24000)
                    
                    # Stream WAV in chunks for consistency
                    chunk_size = 8192
                    chunk_count = 0
                    for i in range(0, len(wav_data), chunk_size):
                        chunk = wav_data[i:i + chunk_size]
                        chunk_count += 1
                        yield chunk
                    
                    logger.info(f"✅ Kokoro: Generated {len(wav_data):,} bytes WAV in {chunk_count} chunks")
                else:
                    # Raw PCM chunks (not recommended for browsers)
                    chunk_count = 0
                    for pcm_chunk in all_pcm_chunks:
                        chunk_count += 1
                        yield pcm_chunk
                    
                    logger.info(f"✅ Kokoro: {chunk_count} PCM chunks generated")
                
                # Success - reset failure counter
                self.consecutive_failures = 0
                return
                
            except Exception as e:
                last_error = e
                logger.warning(f"⚠️ Kokoro attempt {attempt + 1}/{max_retries} failed: {e}")
                
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.5)
                else:
                    self.consecutive_failures += 1
                    if last_error:
                        raise last_error
    
    async def _generate_edge_chunks(
        self,
        text: str,
        voice: str,
        rate: str = "+15%",
        pitch: str = "-0Hz",
        max_retries: int = 2
    ) -> AsyncGenerator[AudioBytes, None]:
        """Generate audio chunks using Edge TTS (fallback)"""
        try:
            import edge_tts
        except ImportError:
            raise RuntimeError("edge-tts not installed. Install: pip install edge-tts")
        
        last_error: Optional[Exception] = None
        
        for attempt in range(max_retries):
            try:
                logger.info(f"🔄 EdgeTTS generating: voice={voice}")
                communicator = edge_tts.Communicate(
                    text=text,
                    voice=voice,
                    rate=rate,
                    pitch=pitch
                )
                
                chunk_count = 0
                async for chunk in communicator.stream():
                    if chunk.get("type") != "audio":
                        continue
                    
                    audio_bytes: Optional[bytes] = chunk.get("data")
                    if not audio_bytes:
                        continue
                    
                    chunk_count += 1
                    yield audio_bytes
                
                if chunk_count == 0:
                    raise Exception("No audio chunks generated")
                
                self.consecutive_failures = 0
                logger.info(f"✅ EdgeTTS: {chunk_count} chunks generated successfully")
                return
                
            except Exception as e:
                last_error = e
                logger.warning(f"⚠️ EdgeTTS attempt {attempt + 1}/{max_retries} failed: {e}")
                
                if attempt < max_retries - 1:
                    await asyncio.sleep(1.0)
                else:
                    self.consecutive_failures += 1
                    if last_error:
                        raise last_error
    
    async def _generate_gtts_chunks(
        self,
        text: str,
        language: str = "en"
    ) -> AsyncGenerator[AudioBytes, None]:
        """Last resort fallback to gTTS"""
        try:
            from gtts import gTTS
        except ImportError:
            raise RuntimeError("gtts not installed. Install: pip install gtts")
        
        logger.info(f"🔄 gTTS generating: language={language}")
        
        # Run gTTS in executor (it's blocking)
        def generate_audio() -> BytesIO:
            tts = gTTS(text=text, lang=language, slow=False)
            audio_buffer = BytesIO()
            tts.write_to_fp(audio_buffer)
            audio_buffer.seek(0)
            return audio_buffer
        
        audio_buffer = await asyncio.get_event_loop().run_in_executor(
            None, generate_audio
        )
        
        # Yield in chunks
        chunk_size = 4096
        chunk_count = 0
        while True:
            chunk = audio_buffer.read(chunk_size)
            if not chunk:
                break
            chunk_count += 1
            yield chunk
        
        self.consecutive_failures = 0
        logger.info(f"✅ gTTS: {chunk_count} chunks generated successfully")
    
    async def generate_audio_stream(
        self,
        text: str,
        lang: Optional[str] = None,
        gender: Optional[str] = None,
        speed: float = 1.0,
        randomize_voice: bool = False,
        use_cache: bool = True
    ) -> AsyncGenerator[AudioBytes, None]:
        """
        Smart audio generation with language-based caching
        
        ✅ NOW OUTPUTS WAV FORMAT FOR BROWSER PLAYBACK
        
        Args:
            text: Text to convert to speech
            lang: Language code ('hi', 'en', 'hindi', 'english', etc.)
                  If None, will auto-detect from text
            gender: 'male' or 'female' (optional, uses default if None)
            speed: Speech speed (0.5 to 2.0)
            randomize_voice: Randomly pick from available voices
            use_cache: Enable caching for this request
        
        Yields:
            Audio chunks as bytes (WAV format)
        """
        
        # Auto-detect language if not provided
        if not lang:
            lang = VoiceSelector.detect_language(text)
            logger.info(f"🔍 Auto-detected language: {lang}")
        
        # Get the best voice automatically
        voice = VoiceSelector.get_voice(lang, gender, randomize_voice)
        lang_code = VoiceSelector.get_kokoro_lang_code(lang)
        
        # Check cache first
        if use_cache:
            cache_key = self._get_cache_key(text, voice, speed)
            cached_audio = self.language_cache.get(cache_key, lang, voice)
            
            if cached_audio:
                # Stream cached audio in chunks for consistency
                chunk_size = 8192
                for i in range(0, len(cached_audio), chunk_size):
                    yield cached_audio[i:i + chunk_size]
                return
        
        logger.info(f"🎵 Generating: lang={lang}, gender={gender or 'auto'}, voice={voice}")
        
        # Generate audio and collect for caching
        audio_chunks: List[AudioBytes] = []
        
        # Try Kokoro first (now with WAV output)
        if self.consecutive_failures < self.max_consecutive_failures:
            try:
                async for chunk in self._generate_kokoro_chunks(
                    text, voice, lang_code, speed, output_format="wav"
                ):
                    audio_chunks.append(chunk)
                    yield chunk
                
                # Cache successful generation
                if use_cache and audio_chunks:
                    complete_audio = b"".join(audio_chunks)
                    self.language_cache.put(cache_key, complete_audio, lang, voice)
                return
                
            except Exception as e:
                logger.warning(f"⚠️ Kokoro failed: {e}, trying fallback...")
                audio_chunks.clear()
        
        # Try Edge TTS fallback (already outputs MP3)
        edge_voice = VoiceSelector.get_edge_voice(lang, gender or "female")
        if edge_voice:
            try:
                logger.info(f"🔄 Using Edge TTS fallback: {edge_voice}")
                async for chunk in self._generate_edge_chunks(text, edge_voice):
                    audio_chunks.append(chunk)
                    yield chunk
                
                # Cache successful generation
                if use_cache and audio_chunks:
                    complete_audio = b"".join(audio_chunks)
                    self.language_cache.put(cache_key, complete_audio, lang, voice)
                return
                
            except Exception as e:
                logger.warning(f"⚠️ Edge TTS failed: {e}, trying gTTS...")
                audio_chunks.clear()
        
        # Last resort: gTTS (outputs MP3)
        try:
            gtts_lang = VoiceSelector.get_gtts_lang(lang)
            logger.info(f"🔄 Using gTTS fallback: {gtts_lang}")
            async for chunk in self._generate_gtts_chunks(text, gtts_lang):
                audio_chunks.append(chunk)
                yield chunk
            
            # Cache successful generation
            if use_cache and audio_chunks:
                complete_audio = b"".join(audio_chunks)
                self.language_cache.put(cache_key, complete_audio, lang, voice)
                    
        except Exception as fallback_error:
            logger.error(f"❌ All TTS providers failed: {fallback_error}")
            raise Exception("All TTS providers unavailable. Please try again later.")
    
    async def generate_complete_audio(
        self,
        text: str,
        lang: Optional[str] = None,
        gender: Optional[str] = None,
        speed: float = 1.0,
        randomize_voice: bool = False,
        use_cache: bool = True
    ) -> AudioBytes:
        """
        Generate complete audio file (optimized for language-based caching)
        
        Returns:
            Complete audio as bytes (WAV format)
        """
        logger.info(f"📦 Generating complete audio")
        
        chunks: List[AudioBytes] = []
        async for chunk in self.generate_audio_stream(
            text, lang, gender, speed, randomize_voice, use_cache
        ):
            chunks.append(chunk)
        
        complete_audio = b"".join(chunks)
        logger.info(f"✅ Generated {len(complete_audio):,} bytes total")
        return complete_audio
    
    async def stream_to_socket(
        self,
        sio: Any,
        sid: str,
        text: str,
        lang: Optional[str] = None,
        gender: Optional[str] = None,
        speed: float = 1.0,
        chunk_delay: float = 0.0
    ) -> bool:
        """
        Stream TTS audio to WebSocket (with language-based caching)
        
        ✅ NOW SENDS WAV FORMAT
        
        Args:
            sio: SocketIO instance
            sid: Socket ID
            text: Text to synthesize
            lang: Language code
            gender: Voice gender
            speed: Speech speed
            chunk_delay: Delay between chunks (for rate limiting)
        
        Returns:
            True if successful, False otherwise
        """
        logger.info(f"🔌 Streaming to socket {sid}")
        
        await sio.emit("tts-start", {
            "text": text[:50] + "..." if len(text) > 50 else text,
            "lang": lang or "auto-detect",
            "gender": gender or "auto"
        }, to=sid)
        
        try:
            chunk_count = 0
            async for audio_bytes in self.generate_audio_stream(
                text, lang, gender, speed
            ):
                await sio.emit("tts-chunk", audio_bytes, to=sid)
                chunk_count += 1
                
                if chunk_delay > 0:
                    await asyncio.sleep(chunk_delay)
            
            logger.info(f"✅ Streamed {chunk_count} chunks to {sid}")
            await sio.emit("tts-end", {"success": True, "chunks": chunk_count}, to=sid)
            return True
            
        except Exception as e:
            logger.exception(f"❌ Stream error: {e}")
            await sio.emit("tts-end", {"success": False, "error": str(e)}, to=sid)
            return False
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get comprehensive cache statistics"""
        stats = self.language_cache.get_stats()
        stats["kokoro_available"] = self.kokoro_available
        stats["consecutive_failures"] = self.consecutive_failures
        return stats
    
    def clear_cache(self, lang: Optional[str] = None) -> None:
        """Clear cache (all languages or specific language)"""
        self.language_cache.clear(lang)


# Global singleton instance
tts_service = TTSService(
    cache_size_per_lang=50,
    cache_ttl=3600
)