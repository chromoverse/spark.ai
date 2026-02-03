# In your REST API routes file

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from app.services.tts_services import tts_service
from pydantic import BaseModel

router = APIRouter()

class TTSRequest(BaseModel):
    text: str
    voice: str = "en-US-BrianNeural"
    rate: str = "+15%"
    pitch: str = "-5Hz"


@router.post("/tts/stream")
async def stream_tts_endpoint(payload: TTSRequest):
    """Stream TTS audio"""
    try:
        return StreamingResponse(
            tts_service.generate_audio_stream(
                text=payload.text,
                voice=payload.voice,
                rate=payload.rate,
                pitch=payload.pitch
            ),
            media_type="audio/mpeg"
        )
    except Exception as e:

        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tts/complete")
async def complete_tts_endpoint(payload: TTSRequest):
    """Generate complete TTS audio file"""
    try:
        audio_data = await tts_service.generate_complete_audio(
            text=payload.text,
            voice=payload.voice,
            rate=payload.rate,
            pitch=payload.pitch
        )
        
        return StreamingResponse(
            iter([audio_data]),
            media_type="audio/mpeg",
            headers={
                "Content-Length": str(len(audio_data)),
                "Content-Disposition": "attachment; filename=speech.mp3"
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))