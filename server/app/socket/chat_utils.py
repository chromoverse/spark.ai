"""
Chat Utilities - Socket event handlers for text and voice queries.

Registers:
    send-user-text-query   → parallel stream + chat execution
    user-speaking          → PCM/webm chunk → transcribe → store in session
    user-stop-speaking     → assemble transcript → parallel stream + chat
"""

import asyncio
<<<<<<< HEAD
import logging

=======
import time
>>>>>>> 7ff3f566494ef823f1013bcd9bc269d63d0fb839
from app.socket.server import sio
from app.socket.user_utils import get_user_from_session, serialize_response
from app.socket.utils import emit_server_status
from app.services.chat.chat_service import chat
from app.services.chat.stream_service import stream_chat_response
from app.services.stt_session_manager import stt_session_manager
from app.services.stt_services import transcribe_audio
from app.services.tts_services import tts_service

logger = logging.getLogger(__name__)

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
    async def _stream() -> None:
        try:
            await stream_chat_response(
                query=query,
                user_id=user_id,
                sio=sio,
                sid=sid,
                tts_service=tts_service,
<<<<<<< HEAD
                gender=gender,
                voice_name=voice_name,
=======
                latency_trace=None,
>>>>>>> 7ff3f566494ef823f1013bcd9bc269d63d0fb839
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

<<<<<<< HEAD
    @sio.on("user-speaking") # type: ignore
=======
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
            if text and text not in _INVALID_TRANSCRIPTIONS:
                await sio.emit("processing", {"status": "Getting response..."}, to=sid)

                result = await parallel_chat_execution(
                    query=text,
                    user_id=user_id,
                    sio=sio,
                    sid=sid,
                    tts_service=tts_service,
                    latency_trace=None,
                )

                chat_result = result.get("chat_result")
                if chat_result:
                    response_data = chat_result.model_dump(by_alias=True)
                    await sio.emit("query-result", response_data, to=sid)
                    logger.info(f"✅ Sent complete query-result to {sid}")
                else:
                    await sio.emit("query-error", {
                        "error": "Chat processing failed",
                        "success": False
                    }, to=sid)
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

    # ── Streaming STT: continuous chunk handler ────────────────────────────

    async def _transcribe_chunk(
        session_id: str, seq: int, audio_data, mime_type: str
    ):
        """
        Background coroutine — transcribes one audio chunk and stores
        the result.  Runs in parallel with other chunk transcriptions.
        Uses previous chunk's text as context for better continuity.
        """
        try:
            # Retrieve previous chunk text for context continuity (Fix 5)
            previous_text = await stt_session_manager.get_last_chunk_text(session_id)

            text = await transcribe_audio(audio_data, mime_type, previous_text=previous_text)

            if text and text not in _INVALID_TRANSCRIPTIONS:
                await stt_session_manager.add_chunk(session_id, seq, text)
                logger.info(
                    f"🎤 Chunk #{seq} transcribed for session "
                    f"{session_id[:8]}…: '{text}'"
                )
            else:
                logger.debug(
                    f"🎤 Chunk #{seq} for session {session_id[:8]}…: "
                    f"no speech detected, skipping"
                )
        except Exception as e:
            logger.error(
                f"❌ Error transcribing chunk #{seq} for session "
                f"{session_id[:8]}…: {e}",
                exc_info=True,
            )
        finally:
            # Always decrement so wait_for_pending doesn't hang
            await stt_session_manager.decrement_pending(session_id)

    @sio.on("user-speaking")  # type: ignore
>>>>>>> 7ff3f566494ef823f1013bcd9bc269d63d0fb839
    async def handle_user_speaking(sid, data):
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
<<<<<<< HEAD
=======
        speech_end_ts_ms_raw = data.get("timestamp")
        try:
            speech_end_ts_ms = int(speech_end_ts_ms_raw or 0)
        except Exception:
            speech_end_ts_ms = 0

>>>>>>> 7ff3f566494ef823f1013bcd9bc269d63d0fb839
        if not session_id:
            logger.warning("user-stop-speaking: missing sessionId from %s", sid)
            return

        try:
            user_id = await get_user_from_session(sid)

<<<<<<< HEAD
            # Wait for any in-flight chunk transcriptions to finish
=======
            await emit_server_status("Backend Fired Up", "INFO", sid)
            await emit_server_status("Analyzing your data", "INFO", sid)
            stop_started = time.perf_counter()

            # ★ Wait for any in-flight chunk transcriptions to finish
>>>>>>> 7ff3f566494ef823f1013bcd9bc269d63d0fb839
            await stt_session_manager.wait_for_pending(session_id)

            text = await stt_session_manager.get_full_text(session_id)
<<<<<<< HEAD
            await stt_session_manager.cleanup(session_id)

            if not text or text in _INVALID_TRANSCRIPTIONS:
=======
            stt_ready_ms = (time.perf_counter() - stop_started) * 1000
            logger.info(f"✅ Assembled transcription: '{text}'")
            logger.info(
                "⏱️ Voice STT stage complete session=%s stt_ready_ms=%.0f",
                session_id[:8],
                stt_ready_ms,
            )

            # Clean up session memory immediately
            await stt_session_manager.cleanup(session_id)

            # Validate transcription (same checks as legacy handler)
            if text and text not in _INVALID_TRANSCRIPTIONS:
                await sio.emit(
                    "processing", {"status": "Getting response..."}, to=sid
                )

                result = await parallel_chat_execution(
                    query=text,
                    user_id=user_id,
                    sio=sio,
                    sid=sid,
                    tts_service=tts_service,
                    latency_trace={
                        "speech_end_ts_ms": speech_end_ts_ms,
                        "stt_ready_ms": stt_ready_ms,
                    },
                )

                chat_result = result.get("chat_result")
                if chat_result:
                    response_data = chat_result.model_dump(by_alias=True)
                    await sio.emit("query-result", response_data, to=sid)
                    logger.info(f"✅ Sent complete query-result to {sid}")
                else:
                    await sio.emit("query-error", {
                        "error": "Chat processing failed",
                        "success": False
                    }, to=sid)
            else:
>>>>>>> 7ff3f566494ef823f1013bcd9bc269d63d0fb839
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