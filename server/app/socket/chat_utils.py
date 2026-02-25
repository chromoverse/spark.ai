"""
Chat Utilities - Socket event handlers for text and voice queries.

Registers:
    send-user-text-query   → parallel stream + chat execution
    send-user-voice-query  → transcribe → parallel stream + chat execution  (legacy)
    user-speaking          → streaming chunk transcription + session storage
    user-stop-speaking     → assemble full text → parallel stream + chat execution
"""

import logging
import asyncio
from app.socket.server import sio
from app.socket.user_utils import get_user_from_session, serialize_response
from app.socket.utils import emit_server_status
from app.services import transcribe_audio
from app.schemas.schemae import RequestTTS
from app.services.tts_services import tts_service
from app.services.stt_session_manager import stt_session_manager

logger = logging.getLogger(__name__)

# Results that mean "no useful speech"
_INVALID_TRANSCRIPTIONS = frozenset(
    {"", "[No speech detected]", "[Thank you.]", "[Transcription failed]", "[Empty audio file]"}
)


def register_chat_events():
    """
    Register all chat-related socket events on the sio instance.
    Called once during init_socket().
    """

    # Start the background session cleanup loop
    stt_session_manager.start_cleanup_loop()

    # ── Text query (unchanged) ─────────────────────────────────────────────

    @sio.on("send-user-text-query")  # type: ignore
    async def send_user_text_query(sid, data):
        """
        Handle text query — runs stream (TTS) and chat (tools) in parallel.
        """
        logger.info(f"🔥 send_user_text_query triggered for sid: {sid}")

        try:
            user_id = await get_user_from_session(sid)

            query = data.get("query") if isinstance(data, dict) else data
            if not query:
                raise ValueError("No query provided")

            await emit_server_status("Processing your query...", "INFO", sid)

            # Run stream + chat in parallel
            from app.services.stream_service import parallel_chat_execution

            result = await parallel_chat_execution(
                query=query,
                user_id=user_id,
                sio=sio,
                sid=sid,
                tts_service=tts_service,
            )

            chat_result = result.get("chat_result")
            dict_data = await serialize_response(chat_result)

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

    # ── Legacy voice query (kept for backward compat) ──────────────────────

    @sio.on("send-user-voice-query")  # type: ignore
    async def send_user_voice_query(sid, data):
        """
        Handle voice query — transcribe audio, then run stream + chat in parallel.
        (Legacy handler — clients should migrate to user-speaking / user-stop-speaking)
        """
        logger.info(f"🔥 Voice query triggered for sid: {sid}")

        try:
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
            if text and text not in _INVALID_TRANSCRIPTIONS:
                await sio.emit("processing", {"status": "Getting response..."}, to=sid)

                # Run stream + chat in parallel
                from app.services.stream_service import parallel_chat_execution

                result = await parallel_chat_execution(
                    query=text,
                    user_id=user_id,
                    sio=sio,
                    sid=sid,
                    tts_service=tts_service,
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
    async def handle_user_speaking(sid, data):
        """
        Receive a ~2 s audio chunk and fire off a PARALLEL transcription
        task.  The handler returns immediately so the next chunk can be
        processed without waiting for the previous transcription to finish.

        Payload:
            { audio: str (base64), mimeType: str, sessionId: str, seq: int }
        """
        session_id = data.get("sessionId")
        seq = data.get("seq")

        if not session_id or seq is None:
            logger.warning(f"⚠️ user-speaking: missing sessionId/seq from {sid}")
            return

        audio_data = data.get("audio")
        mime_type = data.get("mimeType", "audio/webm")

        if not audio_data:
            logger.warning(
                f"⚠️ user-speaking: empty audio for session "
                f"{session_id[:8]}… seq {seq}"
            )
            return

        # Log size and transport format
        audio_len = len(audio_data) if isinstance(audio_data, (str, bytes)) else 0
        transport = "bytes, binary" if isinstance(audio_data, bytes) else "chars, base64"
        logger.info(
            f"🎤 Chunk #{seq} received for session {session_id[:8]}… "
            f"({audio_len} {transport}, {mime_type})"
        )

        # Mark pending BEFORE spawning the task
        await stt_session_manager.increment_pending(session_id)

        # Fire-and-forget: transcribe in background so chunks run in parallel
        asyncio.create_task(
            _transcribe_chunk(session_id, seq, audio_data, mime_type)
        )

    # ── Streaming STT: user stopped speaking ───────────────────────────────

    @sio.on("user-stop-speaking")  # type: ignore
    async def handle_user_stop_speaking(sid, data):
        """
        User stopped speaking — wait for in-flight transcriptions, assemble
        the full text, then run the same parallel chat execution pipeline
        as the legacy send-user-voice-query handler.

        Payload:
            { sessionId: str }
        """
        session_id = data.get("sessionId")

        if not session_id:
            logger.warning(f"⚠️ user-stop-speaking: missing sessionId from {sid}")
            return

        logger.info(
            f"🔥 user-stop-speaking triggered for sid: {sid}, "
            f"session: {session_id[:8]}…"
        )

        try:
            user_id = await get_user_from_session(sid)

            await emit_server_status("Backend Fired Up", "INFO", sid)
            await emit_server_status("Analyzing your data", "INFO", sid)

            # ★ Wait for any in-flight chunk transcriptions to finish
            await stt_session_manager.wait_for_pending(session_id)

            # Get the full text assembled from all streamed chunks
            text = await stt_session_manager.get_full_text(session_id)
            logger.info(f"✅ Assembled transcription: '{text}'")

            # Clean up session memory immediately
            await stt_session_manager.cleanup(session_id)

            # Validate transcription (same checks as legacy handler)
            if text and text not in _INVALID_TRANSCRIPTIONS:
                await sio.emit(
                    "processing", {"status": "Getting response..."}, to=sid
                )

                # Run stream + chat in parallel — exact same as legacy handler
                from app.services.stream_service import parallel_chat_execution

                result = await parallel_chat_execution(
                    query=text,
                    user_id=user_id,
                    sio=sio,
                    sid=sid,
                    tts_service=tts_service,
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
                logger.info(f"⚠️ No valid speech assembled for {sid}")

        except Exception as e:
            logger.error(
                f"❌ Error in handle_user_stop_speaking: {e}", exc_info=True
            )
            await sio.emit(
                "query-error", {"error": str(e), "success": False}, to=sid
            )
            # Best-effort cleanup
            await stt_session_manager.cleanup(session_id)

    logger.info("✅ Chat event handlers registered (incl. streaming STT)")

