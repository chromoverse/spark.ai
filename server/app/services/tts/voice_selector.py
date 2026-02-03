from typing import Dict, Any, List, Optional
import random
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

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
    ) -> str:
        """
        Automatically select the best voice based on language and gender
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
