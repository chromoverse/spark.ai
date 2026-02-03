import socketio
import logging
from typing import Dict, Set
from app.services.tts_services import tts_service
import asyncio
from app.config import settings
from app.services import transcribe_audio
from app.socket.socket_utils import emit_server_status
from app.cache import load_user 
from app.services.chat_service import chat
from app.schemas.schemae import RequestTTS
from app.helper import model_parser

logger = logging.getLogger(__name__)
from app.jwt import config as jwt

# Create Socket.IO server with increased timeouts
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
    logger=True,
    engineio_logger=True,
    namespaces=["/"],
    ping_timeout=60,
    ping_interval=25,
)

# Create ASGI wrapper
socket_app = socketio.ASGIApp(sio)

# ✅ PRODUCTION-SAFE: Support multiple connections per user
connected_users: Dict[str, Set[str]] = {}  # user_id → set of sids

# ================= CONNECTION EVENTS ================= #

@sio.event
async def connect(sid, environ, auth):
    """
    Called when client connects
    ✅ Authenticate with JWT and save user_id to session
    """
    token = auth.get("token", None)
    if not token:
        logger.warning(f"⚠️ No token provided by client")
        raise ConnectionRefusedError("Missing auth token")
    
    try:
        jwt_payload = jwt.decode_token(token)
        user_id = jwt_payload.get("sub")
        
        if not user_id:
            logger.warning(f"⚠️ Invalid token provided by client")
            raise ConnectionRefusedError("Invalid auth token")
        
        # ✅ CRITICAL: Save user_id to socket session
        await sio.save_session(sid, {
            "user_id": user_id,
            "authenticated": True
        })
        
        # ✅ Track multiple connections per user
        if user_id not in connected_users:
            connected_users[user_id] = set()
        connected_users[user_id].add(sid)
        
        logger.info(f"🟢 User {user_id} connected with sid {sid} (total connections: {len(connected_users[user_id])})")
        return True
        
    except Exception as e:
        logger.error(f"❌ Authentication error: {e}")
        raise ConnectionRefusedError("Authentication failed")

@sio.event
async def disconnect(sid):
    """
    Called when client disconnects
    ✅ Clean up using session data
    """
    try:
        # ✅ Get user_id from session (server-controlled)
        session = await sio.get_session(sid)
        user_id = session.get("user_id")
        
        if user_id and user_id in connected_users:
            connected_users[user_id].discard(sid)
            
            # Clean up empty sets
            if not connected_users[user_id]:
                del connected_users[user_id]
                logger.info(f"👋 User {user_id} fully disconnected (no active connections)")
            else:
                logger.info(f"🔌 User {user_id} disconnected sid {sid} ({len(connected_users[user_id])} connections remaining)")
        else:
            logger.info(f"🔌 Client {sid} disconnected (no user session)")
            
    except Exception as e:
        logger.error(f"❌ Error during disconnect cleanup: {e}")

@sio.event
async def register_user(sid, user_id):
    """
    ⚠️ DEPRECATED: User registration now happens automatically during connect
    This event is kept for backward compatibility but does nothing
    """
    session = await sio.get_session(sid)
    actual_user_id = session.get("user_id")
    
    logger.info(f"ℹ️ Received deprecated register_user event from {sid} (user already authenticated as {actual_user_id})")
    await sio.emit("registered", {"userId": actual_user_id}, to=sid)

# ================= HELPER FUNCTIONS ================= #

async def get_user_from_session(sid: str) -> str:
    """
    ✅ Get authenticated user_id from socket session
    Raises exception if not authenticated
    """
    try:
        session = await sio.get_session(sid)
        user_id = session.get("user_id")
        
        if not user_id:
            raise ValueError("No user_id in session - socket not authenticated")
        
        return user_id
    except Exception as e:
        logger.error(f"❌ Failed to get user from session: {e}")
        raise

async def send_to_user(user_id: str, event: str, data: dict):
    """
    Send event to ALL connections of a specific user
    ✅ Supports multi-device/multi-tab
    """
    if user_id in connected_users:
        sids = connected_users[user_id]
        for sid in sids:
            await sio.emit(event, data, to=sid)
        logger.info(f"📤 Sent {event} to user {user_id} ({len(sids)} connections)")
        return True
    else:
        logger.warning(f"⚠️ User {user_id} not connected")
        return False

def get_connected_users():
    """Get list of connected user IDs"""
    return list(connected_users.keys())

async def serialize_response(chatRes) -> dict:
    """Helper to safely serialize chat response to dict"""
    if chatRes is None:
        return {"error": "No response from chat service"}
    
    if hasattr(chatRes, "model_dump") and callable(getattr(chatRes, "model_dump")):
        return chatRes.model_dump()
    elif hasattr(chatRes, "dict") and callable(getattr(chatRes, "dict")):
        return chatRes.dict()
    else:
        try:
            return dict(chatRes)
        except Exception:
            return {"response": str(chatRes)}

# ==================== MESSAGING EVENTS ====================

@sio.on("request-tts")  # type: ignore
async def request_tts(sid, data: RequestTTS):
    """
    ✅ Uses session-based authentication
    ❌ No longer accepts user_id from client
    """
    logger.info(f"⚡ request-tts from {sid}")
    
    try:
        # ✅ Get user_id from authenticated session
        user_id = await get_user_from_session(sid)
        print("user_id", user_id)
        
        data = model_parser.parse(RequestTTS, data)
        print("data", data)
        await emit_server_status("TTS Request Received", "INFO", sid)
        
        # Validate payload
        if not data.text:
            await sio.emit("response-tts", {"success": False, "error": "Missing text"}, to=sid)
            await emit_server_status("Error: Missing text", "ERROR", sid)
            return

        # Load user preferences using session user_id
        user = await load_user(user_id)
        print("user frmo load_user", user)
        gender = user.get("ai_gender", "").strip().lower()
        lang = user.get("language", "").strip().lower()
        await emit_server_status(f"Loaded user preferences as gender={gender}, language={lang}", "INFO", sid)

        # Note: Don't manually select voice here - let VoiceSelector handle it
        # based on lang/gender. Settings voice names (Edge TTS format like hi-IN-MadhurNeural)
        # are incompatible with Kokoro which uses voice IDs like hf_alpha, hm_omega etc.
        logger.info(f"TTS request for user: {user_id} with lang={lang}, gender={gender}")

        # Stream via service - pass lang and gender for auto voice selection
        success = await tts_service.stream_to_socket(
            sio=sio,
            sid=sid,
            text=data.text,
            voice=None,  # Let VoiceSelector pick the right voice for the engine
            rate="+10%",
            lang=lang,
            gender=gender
        )

        if not success:
            await sio.emit("response-tts", {"success": False, "error": "TTS generation failed"}, to=sid)
            await emit_server_status("Error: TTS generation failed", "ERROR", sid)
            return

        await emit_server_status("TTS generation completed successfully", "INFO", sid)
        
    except Exception as e:
        logger.exception("TTS ERROR:")
        await sio.emit("response-tts", {"success": False, "error": str(e)}, to=sid)

@sio.on("send-user-text-query")  # type: ignore
async def send_user_text_query(sid, data):
    """
    ✅ Uses session-based authentication
    """
    logger.info(f"🔥 send_user_text_query triggered for sid: {sid}")
    
    try:
        # ✅ Get user_id from authenticated session
        user_id = await get_user_from_session(sid)
        
        query = data.get("query") if isinstance(data, dict) else data
        if not query :
            raise ValueError("No query provided")
        
        # If chat is synchronous, run it in a thread so it can be awaited safely
        chatRes = await asyncio.to_thread(chat, query)
        dict_data = await serialize_response(chatRes)
        
        await sio.emit(
            "query-result",
            {"result": dict_data, "success": True},
            to=sid
        )
        logger.info(f"✅ Sent query-result to {sid}")
        
    except Exception as e:
        logger.error(f"❌ Error in send_user_text_query: {e}", exc_info=True)
        await sio.emit(
            "query-result",
            {"error": str(e), "success": False},
            to=sid
        )

@sio.on("send-user-voice-query")  # type: ignore
async def send_user_voice_query(sid, data):
    """
    ✅ Uses session-based authentication
    ❌ No longer trusts user_id from client
    """
    logger.info(f"🔥 Voice query triggered for sid: {sid}")
    
    try:
        # ✅ Get user_id from authenticated session
        user_id = await get_user_from_session(sid)
        
        await emit_server_status("Backend Fired Up", "INFO", sid)
        await emit_server_status("Analyzing your data", "INFO", sid)
        
        if not data:
            logger.error(f"❌ No data received for sid: {sid}")
            await sio.emit("query-error", {"error": "No data received", "success": False}, to=sid)
            await emit_server_status("Error: No data received", "ERROR", sid)
            return
        
        audio_data = data.get("audio")
        mime_type = data.get("mimeType", "audio/webm")
        
        if not audio_data:
            logger.error(f"❌ No audio data in payload for sid: {sid}")
            await sio.emit("query-error", {"error": "No audio data", "success": False}, to=sid)
            await emit_server_status("Audio data not received", "ERROR", sid)
            return
        
        if isinstance(audio_data, str):
            logger.info(f"📊 Received base64 audio: {len(audio_data)} chars, type: {mime_type}")
        elif isinstance(audio_data, bytes):
            logger.info(f"📊 Received binary audio: {len(audio_data)} bytes, type: {mime_type}")
        else:
            logger.error(f"❌ Unexpected audio data type: {type(audio_data)}")
            await sio.emit("query-error", {"error": "Invalid audio format", "success": False}, to=sid)
            return
        
        await sio.emit("processing", {"status": "Transcribing audio..."}, to=sid)
        
        # Transcribe audio
        text = await transcribe_audio(audio_data, mime_type)
        
        logger.info(f"✅ Transcription result: '{text}'")
        
        # Validate transcription
        if text and text not in ["", "[No speech detected]", "[Transcription failed]", "[Empty audio file]"]:
            await sio.emit("processing", {"status": "Getting response..."}, to=sid)
            
            # ✅ Use session user_id (not from client payload)
            chat_res = await chat(text, user_id)  # type: ignore
    

            data = chat_res.model_dump(by_alias=True)

            # also emit the tts response
            tts_data = RequestTTS(
                text=data.get("text", "")
            )
            await request_tts(sid, tts_data)
            
            await sio.emit("query-result", data, to=sid)
            
            logger.info(f"✅ Sent complete query-result to {sid}")
        else:
            await sio.emit("query-error", {
                "result": text,
                "success": False,
                "message": "No speech detected or transcription failed"
            }, to=sid)
            
            logger.info(f"⚠️ No valid speech for {sid}")
        
    except Exception as e:
        logger.error(f"❌ Error in send_user_voice_query: {e}", exc_info=True)
        await sio.emit("query-error", {"error": str(e), "success": False}, to=sid)

__all__ = ["sio"]        