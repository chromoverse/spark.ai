"""
Chat Utilities - Socket event handlers for text and voice queries.

Registers:
    send-user-text-query  → parallel stream + chat execution
    send-user-voice-query → transcribe → parallel stream + chat execution
"""

import logging
import asyncio
from app.socket.server import sio
from app.socket.user_utils import get_user_from_session, serialize_response
from app.socket.utils import emit_server_status
from app.services import transcribe_audio
from app.schemas.schemae import RequestTTS
from app.services.tts_services import tts_service

logger = logging.getLogger(__name__)


def register_chat_events():
    """
    Register all chat-related socket events on the sio instance.
    Called once during init_socket().
    """

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

    @sio.on("send-user-voice-query")  # type: ignore
    async def send_user_voice_query(sid, data):
        """
        Handle voice query — transcribe audio, then run stream + chat in parallel.
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
            invalid_results = ["", "[No speech detected]", "[Transcription failed]", "[Empty audio file]"]
            if text and text not in invalid_results:
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

    logger.info("✅ Chat event handlers registered")
