from fastapi import APIRouter, File, UploadFile, HTTPException
import os
import logging

# ✅ IMPORT WITH DIFFERENT NAME (avoid collision)
from app.services.stt_services import transcribe_audio as process_audio

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".mpga", ".webm", ".mp4", ".ogg"}

MIME_MAP = {
    ".webm": "audio/webm",
    ".wav": "audio/wav",
    ".mp3": "audio/mp3",
    ".mpeg": "audio/mpeg",
    ".m4a": "audio/m4a",
    ".mp4": "audio/mp4",
    ".ogg": "audio/ogg",
    ".mpga": "audio/mpeg",
}


@router.post("/stt")
async def transcribe_audio_endpoint(file: UploadFile = File(...)):
    """
    FastAPI endpoint for speech-to-text transcription.
    
    Accepts audio file upload (multipart/form-data) and returns transcribed text.
    Supports: .wav, .mp3, .m4a, .webm, .mp4, .ogg
    """
    filename = file.filename or "audio.webm"
    ext = os.path.splitext(filename)[1].lower()
    
    # Validate file extension
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext}. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    try:
        # Read uploaded file directly into memory — no temp file needed
        audio_bytes = await file.read()
        
        if len(audio_bytes) < 1000:
            raise HTTPException(
                status_code=400,
                detail="Audio file too small (likely empty or corrupted)"
            )
        
        logger.info(f"📤 Received audio file: {filename} ({len(audio_bytes)} bytes)")
        
        mime_type = MIME_MAP.get(ext, "audio/webm")
        
        # Transcribe directly from bytes — no disk I/O
        text = await process_audio(audio_bytes, mime_type=mime_type)
        
        # Handle transcription errors
        if text.startswith("[") and text.endswith("]"):
            logger.warning(f"⚠️ STT returned error: {text}")
            raise HTTPException(status_code=422, detail=text)
        
        logger.info(f"✅ Transcription successful: '{text}'")
        return {
            "text": text,
            "success": True
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ STT endpoint error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Transcription failed: {str(e)}"
        )