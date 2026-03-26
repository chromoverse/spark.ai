"""
Chat Utilities - Socket event handlers for text and voice queries.

Registers:
    send-user-text-query   → parallel stream + chat execution
    user-speaking          → PCM/webm chunk → transcribe → store + speculative prefetch
    user-stop-speaking     → assemble transcript → use pre-fetched context → LLM fires instantly
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from app.socket.server import sio
from app.socket.user_utils import get_user_from_session, serialize_response
from app.socket.utils import emit_server_status
from app.services.chat.chat_service import chat
from app.services.chat.stream_service import stream_chat_response
from app.services.interrupt_manager import get_interrupt_manager
from app.services.stt_session_manager import stt_session_manager
from app.services.stt_services import transcribe_audio
from app.services.tts_services import tts_service
from app.services.speculative_cache import speculative_cache

logger = logging.getLogger(__name__)
_interrupt = get_interrupt_manager()

_INVALID_TRANSCRIPTIONS = frozenset({
    "", "[No speech detected]", "[Thank you.]",
    "[Transcription failed]", "[Empty audio file]",
})

# ── RAG skip heuristic ────────────────────────────────────────────────────────
_CONVERSATIONAL_WORDS = frozenset({
    "hi", "hello", "hey", "thanks", "thank", "ok", "okay",
    "bye", "yes", "no", "sure", "yeah", "yep", "nope",
    "good", "great", "fine", "cool", "nice", "alright",
    "spark", "hmm", "hm", "uh", "um",
})


def _should_skip_rag(text: str) -> bool:
    """Skip RAG for conversational/short queries that don't need knowledge retrieval."""
    words = text.strip().lower().split()
    if len(words) < 3:
        return True  # "hey spark", "what's up"
    word_set = set(words)
    if word_set & _CONVERSATIONAL_WORDS and len(words) < 6:
        return True  # "hey spark how are you"
    return False


# ── Speculative pre-fetch — runs during speech ───────────────────────────────

async def _speculative_prefetch(session_id: str, user_id: str) -> None:
    """
    Pre-fetch user details, recent messages, and RAG context during speech.
    Called after each chunk transcription completes.
    Results are cached in speculative_cache for instant retrieval on stop-speaking.
    """
    try:
        ctx = await speculative_cache.get_or_create(session_id)

        # Load user details + recent messages ONCE per session
        if not ctx.user_loaded:
            from app.cache import load_user, get_last_n_messages
            try:
                user_task = asyncio.create_task(load_user(user_id))
                recent_task = asyncio.create_task(get_last_n_messages(user_id, n=5))
                ctx.user_details = await user_task
                ctx.recent_messages = await recent_task
                ctx.user_loaded = True
                logger.info("🔍 Speculative prefetch: user+recent loaded for session %s…", session_id[:8])
            except Exception as exc:
                logger.warning("⚠️ Speculative user/recent load failed: %s", exc)

        # Get current partial transcript
        partial = await stt_session_manager.get_current_partial_text(session_id)
        if not partial:
            return
        ctx.partial_transcript = partial

        # Skip RAG for conversational queries
        if _should_skip_rag(partial):
            logger.debug("⏭️ Speculative RAG skipped (conversational): '%s'", partial[:60])
            return

        # Only re-query RAG if transcript has meaningfully changed
        if ctx.rag_query_text == partial or ctx.rag_in_flight:
            return

        ctx.rag_in_flight = True
        ctx.rag_query_text = partial
        try:
            from app.cache import process_query_and_get_context
            result, _ = await asyncio.wait_for(
                process_query_and_get_context(
                    user_id=user_id,
                    query=partial,
                    budget_ms=200,
                    top_k=8,
                    threshold=0.08,
                    fast_lane=True,
                ),
                timeout=0.5,  # aggressive timeout — this is speculative
            )
            ctx.rag_context = result or []
            logger.info(
                "🔍 Speculative RAG: %d results for '%s'",
                len(ctx.rag_context), partial[:60],
            )
        except (asyncio.TimeoutError, Exception) as exc:
            logger.debug("⚠️ Speculative RAG timeout/error (expected): %s", exc)
        finally:
            ctx.rag_in_flight = False
            ctx.touch()

    except Exception as exc:
        logger.error("❌ Speculative prefetch error: %s", exc)


# ── Parallel execution: stream (TTS) + chat (tools) run independently ─────────

async def _parallel_execute(
    query: str,
    user_id: str,
    sid: str,
    voice_name: str | None = None,
    gender: str = "female",
    pre_fetched_context: Optional[Dict[str, Any]] = None,
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
                pre_fetched_context=pre_fetched_context,
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

async def _transcribe_chunk(session_id: str, seq: int, audio_data: Any, mime_type: str) -> None:
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
    speculative_cache.start_cleanup_loop()

    # ── Text query ─────────────────────────────────────────────────────────

    @sio.on("send-user-text-query") # type: ignore
    async def send_user_text_query(sid: str, data: Any):
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
    async def handle_user_speaking(sid: str, data: Any):
        session_id = data.get("sessionId")
        seq        = data.get("seq")
        audio_data = data.get("audio")
        mime_type  = data.get("mimeType", "audio/webm")

        if not session_id or seq is None or not audio_data:
            logger.warning("user-speaking: bad payload from %s", sid)
            return

        await stt_session_manager.increment_pending(session_id)
        asyncio.create_task(_transcribe_chunk(session_id, seq, audio_data, mime_type))

        # ⚡ Speculative pre-fetch: fire after each chunk to pre-load context
        try:
            user_id = await get_user_from_session(sid)
            asyncio.create_task(_speculative_prefetch(session_id, user_id))
        except Exception:
            pass  # non-critical — prefetch is best-effort

    # ── Speech started signal — pre-load context before audio arrives ─────

    @sio.on("user-speech-started") # type: ignore
    async def handle_user_speech_started(sid: str, data: Any):
        """
        Fired the INSTANT speech is detected — before any audio chunk arrives.
        Triggers speculative pre-fetch of user details + recent messages.
        """
        session_id = data.get("sessionId") if isinstance(data, dict) else None
        if not session_id:
            return
        try:
            user_id = await get_user_from_session(sid)
            logger.info("⚡ user-speech-started: pre-fetching context for session %s…", session_id[:8])
            asyncio.create_task(_speculative_prefetch(session_id, user_id))
        except Exception:
            pass  # non-critical

    # ── Streaming STT: user stopped speaking ──────────────────────────────

    @sio.on("user-stop-speaking") # type: ignore
    async def handle_user_stop_speaking(sid: str, data: Any):
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
                await speculative_cache.cleanup(session_id)
                return

            # ⚡ Grab pre-fetched context from speculative cache
            pre_fetched: Optional[Dict[str, Any]] = None
            cached_ctx = await speculative_cache.pop(session_id)
            if cached_ctx and cached_ctx.user_loaded:
                pre_fetched = {
                    "user_details": cached_ctx.user_details,
                    "recent_messages": cached_ctx.recent_messages,
                    "rag_context": cached_ctx.rag_context,
                }
                logger.info(
                    "⚡ Using speculative context: user=%s, rag=%d chunks",
                    bool(cached_ctx.user_details),
                    len(cached_ctx.rag_context or []),
                )

            result = await _parallel_execute(
                query=text, user_id=user_id, sid=sid,
                pre_fetched_context=pre_fetched,
            )

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
            await speculative_cache.cleanup(session_id)

    # ── User interrupt: stop all TTS for this user ────────────────────────

    @sio.on("user-interrupt")  # type: ignore
    async def handle_user_interrupt(sid: str, data: Any):
        try:
            user_id = await get_user_from_session(sid)
            _interrupt.set(user_id)
            # Confirm back to client so it can stop playback immediately
            await sio.emit("tts-interrupt", {}, to=sid)
            logger.info("🛑 user-interrupt from %s (user=%s)", sid, user_id)
        except Exception as exc:
            logger.error("user-interrupt failed sid=%s: %s", sid, exc)