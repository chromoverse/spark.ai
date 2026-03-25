"""
Chat Utilities - Socket event handlers for text and voice queries.

Registers:
    send-user-text-query   → parallel stream + chat execution
    user-speaking          → PCM/webm chunk → transcribe → store in session
    user-stop-speaking     → assemble transcript → parallel stream + chat
"""

import asyncio
import logging

from app.socket.server import sio
from app.socket.user_utils import get_user_from_session, serialize_response
from app.socket.utils import emit_server_status
from app.services.chat.chat_service import chat
from app.services.chat.stream_service import stream_chat_response
from app.services.interrupt_manager import get_interrupt_manager
from app.services.stt_session_manager import stt_session_manager
from app.services.stt_services import transcribe_audio
from app.services.tts_services import tts_service

logger = logging.getLogger(__name__)
_interrupt = get_interrupt_manager()

_INVALID_TRANSCRIPTIONS = frozenset({
    "", "[No speech detected]", "[Thank you.]",
    "[Transcription failed]", "[Empty audio file]",
})


# ── Parallel execution: stream (TTS) + chat (tools) run independently ─────────
#
#   Stream path  → immediate audio feedback to the user via TTS
#   Chat path    → PQH → tool dispatch (SQH) — heavier, runs in background
#
#   They don't depend on each other. Stream doesn't need chat's result.
#   Chat doesn't need stream's result. Fire both, await chat for query-result.

async def _parallel_execute(
    query: str,
    user_id: str,
    sid: str,
    voice_name: str | None = None,
    gender: str = "female",
) -> dict:
    # Clear any previous interrupt so this request runs cleanly
    _interrupt.clear(user_id)

    async def _stream() -> None:
        try:
            await stream_chat_response(
                query=query,
                user_id=user_id,
                sio=sio,
                sid=sid,
                tts_service=tts_service,
                gender=gender,
                voice_name=voice_name,
            )
        except Exception as exc:
            logger.error("stream path failed for %s: %s", sid, exc)

    # Stream fires immediately as a background task — user hears audio ASAP
    stream_task = asyncio.create_task(_stream())

    # Chat runs concurrently — handles tool execution
    chat_result = None
    try:
        chat_result = await chat(query=query, user_id=user_id, wait_for_execution=False)
    except Exception as exc:
        logger.error("chat path failed for %s: %s", sid, exc)

    return {"stream_task": stream_task, "chat_result": chat_result}


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _transcribe_chunk(session_id: str, seq: int, audio_data, mime_type: str) -> None:
    """Transcribe one audio chunk in the background and store result."""
    try:
        previous_text = await stt_session_manager.get_last_chunk_text(session_id)
        text = await transcribe_audio(audio_data, mime_type, previous_text=previous_text)
        if text and text not in _INVALID_TRANSCRIPTIONS:
            await stt_session_manager.add_chunk(session_id, seq, text)
    except Exception as exc:
        logger.error("chunk #%d transcription failed session=%s: %s", seq, session_id[:8], exc)
    finally:
        await stt_session_manager.decrement_pending(session_id)


# ── Event registration ─────────────────────────────────────────────────────────

def register_chat_events():
    stt_session_manager.start_cleanup_loop()

    # ── Text query ─────────────────────────────────────────────────────────

    @sio.on("send-user-text-query") # type: ignore
    async def send_user_text_query(sid, data):
        try:
            user_id = await get_user_from_session(sid)
            query = (data.get("query") if isinstance(data, dict) else data or "").strip() # type: ignore
            if not query:
                raise ValueError("No query provided")

            result = await _parallel_execute(query=query, user_id=user_id, sid=sid)

            dict_data = await serialize_response(result.get("chat_result"))
            await sio.emit("query-result", {"result": dict_data, "success": True}, to=sid)

        except Exception as exc:
            logger.error("send_user_text_query failed sid=%s: %s", sid, exc)
            await sio.emit("query-result", {"error": str(exc), "success": False}, to=sid)

    # ── Streaming STT: receive audio chunk ────────────────────────────────

    @sio.on("user-speaking") # type: ignore
    async def handle_user_speaking(sid, data):
        # TODO: add more error handling
        session_id = data.get("sessionId")
        seq        = data.get("seq")
        audio_data = data.get("audio")
        mime_type  = data.get("mimeType", "audio/webm")

        if not session_id or seq is None or not audio_data:
            logger.warning("user-speaking: bad payload from %s", sid)
            return

        await stt_session_manager.increment_pending(session_id)
        asyncio.create_task(_transcribe_chunk(session_id, seq, audio_data, mime_type))

    # ── Streaming STT: user stopped speaking ──────────────────────────────

    @sio.on("user-stop-speaking") # type: ignore
    async def handle_user_stop_speaking(sid, data):
        session_id = data.get("sessionId")
        if not session_id:
            logger.warning("user-stop-speaking: missing sessionId from %s", sid)
            return

        try:
            user_id = await get_user_from_session(sid)

            # Wait for any in-flight chunk transcriptions to finish
            await stt_session_manager.wait_for_pending(session_id)

            text = await stt_session_manager.get_full_text(session_id)
            await stt_session_manager.cleanup(session_id)

            if not text or text in _INVALID_TRANSCRIPTIONS:
                await sio.emit("query-error", {
                    "success": False,
                    "message": "No speech detected",
                }, to=sid)
                return

            result = await _parallel_execute(query=text, user_id=user_id, sid=sid)

            chat_result = result.get("chat_result")
            if chat_result:
                response_data = chat_result.model_dump(by_alias=True)
                await sio.emit("query-result", response_data, to=sid)
            else:
                await sio.emit("query-error", {"error": "Chat failed", "success": False}, to=sid)

        except Exception as exc:
            logger.error("user-stop-speaking failed sid=%s: %s", sid, exc)
            await sio.emit("query-error", {"error": str(exc), "success": False}, to=sid)
            await stt_session_manager.cleanup(session_id)

    # ── User interrupt: stop all TTS for this user ────────────────────────

    @sio.on("user-interrupt")  # type: ignore
    async def handle_user_interrupt(sid, data):
        try:
            user_id = await get_user_from_session(sid)
            _interrupt.set(user_id)
            # Confirm back to client so it can stop playback immediately
            await sio.emit("tts-interrupt", {}, to=sid)
            logger.info("🛑 user-interrupt from %s (user=%s)", sid, user_id)
        except Exception as exc:
            logger.error("user-interrupt failed sid=%s: %s", sid, exc)