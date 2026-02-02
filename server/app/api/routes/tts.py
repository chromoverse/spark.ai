# app/api/routes/tts.py
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, Literal

# Import the simplified service
from app.services.tts_services import tts_service, VoiceSelector

router = APIRouter(prefix="/tts", tags=["TTS"])


class TTSRequest(BaseModel):
    """
    Super simple TTS request - just text, language, and gender!
    No need to remember complex voice names!
    """
    text: str = Field(
        ..., 
        description="Text to convert to speech",
        min_length=1,
        max_length=5000,
        examples=["नमस्ते! आप कैसे हैं?", "Hello, how are you?"]
    )
    lang: Optional[str] = Field(
        default=None,
        description=(
            "Language: 'hi'/'hindi', 'en'/'english', 'ja'/'japanese', "
            "'zh'/'chinese', 'es'/'spanish', 'fr'/'french', 'it'/'italian', 'pt'/'portuguese'. "
            "If not provided, language will be auto-detected!"
        ),
        examples=["hi", "hindi", "en", "english"]
    )
    gender: Optional[Literal["male", "female"]] = Field(
        default=None,
        description="Voice gender: 'male' or 'female'. If not provided, uses default for language."
    )
    speed: Optional[float] = Field(
        default=1.0,
        description="Speech speed (0.5 = slow, 1.0 = normal, 2.0 = fast)",
        ge=0.5,
        le=2.0
    )
    randomize_voice: Optional[bool] = Field(
        default=False,
        description="Randomly pick from available voices for variety"
    )
    
    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "text": "नमस्ते! मैं आपकी मदद के लिए यहाँ हूँ।",
                    "lang": "hi",
                    "gender": "female",
                    "speed": 1.0
                },
                {
                    "text": "Hello! I'm here to help you.",
                    "lang": "en",
                    "gender": "male",
                    "speed": 1.1
                },
                {
                    "text": "Auto-detect my language!",
                    "speed": 1.0
                }
            ]
        }


@router.post("/speak")
async def speak_endpoint(payload: TTSRequest):
    """
    🎯 Main TTS endpoint - Super Simple!
    
    Just provide:
    - text: What to say
    - lang: Which language (optional, auto-detects!)
    - gender: male/female (optional, uses default)
    
    No need to remember voice names! The system picks the best voice automatically.
    
    Examples:
    - Hindi female: {"text": "नमस्ते", "lang": "hi", "gender": "female"}
    - English male: {"text": "Hello", "lang": "en", "gender": "male"}
    - Auto-detect: {"text": "नमस्ते"} (detects Hindi automatically!)
    """
    try:
        return StreamingResponse(
            tts_service.generate_audio_stream(
                text=payload.text,
                lang=payload.lang,
                gender=payload.gender,
                speed=payload.speed or 1.0,
                randomize_voice=payload.randomize_voice or False
            ),
            media_type="audio/mpeg",
            headers={
                "Cache-Control": "no-cache",
                "X-Content-Type-Options": "nosniff"
            }
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS generation failed: {str(e)}")


@router.post("/stream")
async def stream_tts_endpoint(payload: TTSRequest):
    """
    🎵 Stream TTS audio (alias for /speak)
    """
    return await speak_endpoint(payload)


@router.post("/download")
async def download_tts_endpoint(payload: TTSRequest):
    """
    💾 Generate complete audio file for download
    
    Same simple interface - just text, lang, and gender!
    Returns a complete MP3 file ready for download.
    """
    try:
        audio_data = await tts_service.generate_complete_audio(
            text=payload.text,
            lang=payload.lang,
            gender=payload.gender,
            speed=payload.speed or 1.0,
            randomize_voice=payload.randomize_voice or False
        )
        
        return StreamingResponse(
            iter([audio_data]),
            media_type="audio/mpeg",
            headers={
                "Content-Length": str(len(audio_data)),
                "Content-Disposition": 'attachment; filename="speech.mp3"',
                "Cache-Control": "public, max-age=3600"
            }
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS generation failed: {str(e)}")


@router.get("/languages")
async def list_languages():
    """
    🌍 List all supported languages
    
    Returns available languages with their codes and default genders.
    """
    languages = {}
    
    for lang_code, config in VoiceSelector.VOICE_MAP.items():
        # Skip duplicates (aliases)
        if lang_code in languages:
            continue
            
        has_male = len(config.get("male", [])) > 0
        has_female = len(config.get("female", [])) > 0
        
        languages[lang_code] = {
            "code": lang_code,
            "has_male": has_male,
            "has_female": has_female,
            "default_gender": config.get("default_gender", "female"),
            "male_voices_count": len(config.get("male", [])),
            "female_voices_count": len(config.get("female", []))
        }
    
    return {
        "languages": languages,
        "total_languages": len(languages),
        "supported_codes": list(languages.keys()),
        "note": "You can use language names too! e.g., 'hindi', 'english', 'spanish'"
    }


@router.get("/languages/{lang}")
async def get_language_info(lang: str):
    """
    📋 Get detailed info about a specific language
    
    Shows available genders and voice counts for the language.
    """
    lang_config = VoiceSelector.VOICE_MAP.get(lang.lower())
    
    if not lang_config:
        raise HTTPException(
            status_code=404,
            detail=f"Language '{lang}' not found. Use /tts/languages to see available languages."
        )
    
    return {
        "language": lang,
        "default_gender": lang_config.get("default_gender"),
        "available_genders": {
            "male": {
                "available": len(lang_config.get("male", [])) > 0,
                "count": len(lang_config.get("male", []))
            },
            "female": {
                "available": len(lang_config.get("female", [])) > 0,
                "count": len(lang_config.get("female", []))
            }
        },
        "usage_example": {
            "text": "Your text here",
            "lang": lang,
            "gender": lang_config.get("default_gender")
        }
    }


@router.post("/test")
async def quick_test(
    text: str = Query(
        default="Hello! This is a test.",
        description="Text to test",
        max_length=200
    ),
    lang: Optional[str] = Query(
        default=None,
        description="Language code (e.g., 'hi', 'en')"
    ),
    gender: Optional[str] = Query(
        default=None,
        description="Gender: 'male' or 'female'"
    )
):
    """
    🧪 Quick test endpoint
    
    Test different languages and genders quickly!
    
    Examples:
    - /tts/test?text=नमस्ते&lang=hi&gender=female
    - /tts/test?text=Hello&lang=en&gender=male
    - /tts/test?text=नमस्ते (auto-detect language)
    """
    try:
        return StreamingResponse(
            tts_service.generate_audio_stream(
                text=text,
                lang=lang,
                gender=gender,
                speed=1.0
            ),
            media_type="audio/mpeg"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """
    ❤️ Check TTS service health
    """
    return {
        "status": "healthy",
        "kokoro_available": tts_service.kokoro_available,
        "kokoro_initialized": tts_service.kokoro_initialized,
        "consecutive_failures": tts_service.consecutive_failures,
        "service": "simplified-tts",
        "note": "No voice names needed - just use language and gender!"
    }


@router.get("/examples")
async def usage_examples():
    """
    📚 Get usage examples for different languages
    """
    return {
        "examples": [
            {
                "language": "Hindi",
                "code": "hi",
                "curl": """curl -X POST "http://localhost:8000/tts/speak" \\
  -H "Content-Type: application/json" \\
  -d '{"text": "नमस्ते! आप कैसे हैं?", "lang": "hi", "gender": "female"}' \\
  --output hindi_female.mp3""",
                "json": {
                    "text": "नमस्ते! आप कैसे हैं?",
                    "lang": "hi",
                    "gender": "female"
                }
            },
            {
                "language": "English",
                "code": "en",
                "curl": """curl -X POST "http://localhost:8000/tts/speak" \\
  -H "Content-Type: application/json" \\
  -d '{"text": "Hello! How are you?", "lang": "en", "gender": "male"}' \\
  --output english_male.mp3""",
                "json": {
                    "text": "Hello! How are you?",
                    "lang": "en",
                    "gender": "male"
                }
            },
            {
                "language": "Auto-detect",
                "code": "auto",
                "curl": """curl -X POST "http://localhost:8000/tts/speak" \\
  -H "Content-Type: application/json" \\
  -d '{"text": "नमस्ते"}' \\
  --output auto_detect.mp3""",
                "json": {
                    "text": "नमस्ते (Hindi text will be auto-detected!)"
                },
                "note": "Language auto-detection works! Just provide text."
            }
        ],
        "javascript_example": {
            "description": "Simple JavaScript usage",
            "code": """const response = await fetch('http://localhost:8000/tts/speak', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    text: 'नमस्ते! मैं कोकोरो हूं।',
    lang: 'hi',      // or 'hindi'
    gender: 'female', // or 'male'
    speed: 1.0       // optional
  })
});

const audioBlob = await response.blob();
const audio = new Audio(URL.createObjectURL(audioBlob));
audio.play();"""
        },
        "python_example": {
            "description": "Python usage",
            "code": """import asyncio
from app.services.tts_service_with_fallback import tts_service

# Super simple!
async def generate_speech():
    audio_chunks = []
    async for chunk in tts_service.generate_audio_stream(
        text="नमस्ते! मैं आपकी मदद करूंगा।",
        lang="hi",        # or "hindi"
        gender="female"   # or "male"
    ):
        audio_chunks.append(chunk)
    
    with open("output.mp3", "wb") as f:
        f.write(b"".join(audio_chunks))

asyncio.run(generate_speech())"""
        }
    }


# Backward compatibility - old endpoint names still work
@router.post("/complete")
async def complete_tts_legacy(payload: TTSRequest):
    """Legacy endpoint - use /download instead"""
    return await download_tts_endpoint(payload)