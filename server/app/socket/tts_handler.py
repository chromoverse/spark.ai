"""
Updated WebSocket Handler for TTS Requests

This integrates with the new streaming architecture:
- Uses FreeFlowLLM for AI responses
- Streams text chunks at sentence boundaries
- Generates audio in real-time
- Sends audio chunks to frontend instantly
"""
import logging
from typing import Any, Callable, Awaitable
from app.schemas.schemae import RequestTTS
from app.socket.utils import emit_server_status
from app.cache import load_user
from app.services.stream_service import stream_chat_response

logger = logging.getLogger(__name__)


async def handle_tts_request(
    sio: Any,
    sid: str,
    data: RequestTTS,
    tts_service: Any,
    get_user_from_session: Callable[[str], Awaitable[str]]
) -> None:
    """
    Handle TTS request with streaming AI response.
    
    This is the new handler that replaces the old request-tts handler.
    
    Flow:
    1. Authenticate user
    2. Load user preferences
    3. Stream AI response
    4. Chunk at sentence boundaries
    5. Generate audio for each sentence
    6. Send audio chunks to frontend
    
    Args:
        sio: Socket.IO instance
        sid: Session ID
        data: RequestTTS model with text/query
        tts_service: TTS service instance
        get_user_from_session: Function to get user_id from session
    """
    logger.info(f"⚡ request-tts from {sid}")
    
    try:
        # ✅ Get user_id from authenticated session
        user_id = await get_user_from_session(sid)
        logger.info(f"User: {user_id}")
        
        await emit_server_status("TTS Request Received", "INFO", sid)
        
        # Validate payload
        if not data.text:
            await sio.emit(
                "response-tts",
                {"success": False, "error": "Missing text"},
                to=sid
            )
            await emit_server_status("Error: Missing text", "ERROR", sid)
            return
        
        # Load user preferences
        user = await load_user(user_id)
        gender = user.get("ai_gender", "").strip().lower()
        lang = user.get("language", "").strip().lower()
        
        await emit_server_status(
            f"Loaded user preferences: gender={gender}, language={lang}",
            "INFO",
            sid
        )
        
        logger.info(f"TTS request: user={user_id}, lang={lang}, gender={gender}")
        
        # ✅ NEW: Stream AI response with TTS
        success = await stream_chat_response(
            query=data.text,
            user_id=user_id,
            sio=sio,
            sid=sid,
            tts_service=tts_service,
            gender=gender
        )
        
        if not success:
            await sio.emit(
                "response-tts",
                {"success": False, "error": "TTS generation failed"},
                to=sid
            )
            await emit_server_status("Error: TTS generation failed", "ERROR", sid)
            return
        
        await emit_server_status("TTS generation completed successfully", "INFO", sid)
        
    except Exception as e:
        logger.exception("TTS ERROR:")
        await sio.emit(
            "response-tts",
            {"success": False, "error": str(e)},
            to=sid
        )


# ==================== SOCKET.IO DECORATOR VERSION ====================

def register_tts_handler(
    sio: Any,
    tts_service: Any,
    get_user_from_session: Callable[[str], Awaitable[str]]
) -> None:
    """
    Register the TTS handler with Socket.IO.
    
    Usage in your WebSocket setup:
        from app.websocket.handlers.tts_handler_new import register_tts_handler
        
        register_tts_handler(sio, tts_service, get_user_from_session)
    """
    
    @sio.on("request-tts")
    async def request_tts(sid: str, data: RequestTTS) -> None:
        """
        ✅ Uses session-based authentication
        ✅ Streams AI response with sentence chunking
        ✅ Real-time TTS generation
        """
        await handle_tts_request(
            sio=sio,
            sid=sid,
            data=data,
            tts_service=tts_service,
            get_user_from_session=get_user_from_session
        )
    
    logger.info("✅ New TTS handler registered with streaming support")


# ==================== ALTERNATIVE: PARALLEL EXECUTION ====================

async def handle_tts_request_with_parallel_chat(
    sio: Any,
    sid: str,
    data: RequestTTS,
    tts_service: Any,
    get_user_from_session: Callable[[str], Awaitable[str]]
) -> None:
    """
    Advanced version that runs TTS stream AND tool execution in parallel.
    
    Use this if you want:
    - Immediate TTS feedback to user
    - Tool execution in background
    - Best of both worlds
    """
    from app.services.stream_service import parallel_chat_execution
    
    logger.info(f"⚡ request-tts-parallel from {sid}")
    
    try:
        user_id = await get_user_from_session(sid)
        user = await load_user(user_id)
        gender = user.get("ai_gender", "").strip().lower()
        
        # Run both TTS stream and chat in parallel
        result = await parallel_chat_execution(
            query=data.text,
            user_id=user_id,
            sio=sio,
            sid=sid,
            tts_service=tts_service,
            gender=gender
        )
        
        if result["stream_success"]:
            await emit_server_status("TTS completed", "INFO", sid)
        else:
            await emit_server_status("TTS failed", "ERROR", sid)
        
        if result["chat_result"]:
            logger.info(f"Chat completed with tools: {result['chat_result'].requested_tool}")
        
    except Exception as e:
        logger.exception("TTS-PARALLEL ERROR:")
        await sio.emit("response-tts", {"success": False, "error": str(e)}, to=sid)