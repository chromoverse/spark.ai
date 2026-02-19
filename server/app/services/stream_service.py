"""
Streaming Chat Service - Real-time AI responses with TTS integration

STREAMING VERSION: Uses llm_stream for real-time token streaming.
Accumulates tokens into chunks of ~15 words before sending to TTS.
TTS starts speaking within 1-2 seconds instead of waiting for full response.
"""
import logging
import asyncio
from typing import Optional, List, Any
from app.ai.providers import llm_stream, llm_chat
from app.cache import load_user, get_last_n_messages
from app.prompts import stream_prompt
from app.config import settings

logger = logging.getLogger(__name__)

# Minimum words per TTS chunk — ensures natural-sounding speech
MIN_CHUNK_WORDS = 15


class StreamService:
    """
    Handles real-time AI responses with TTS.
    
    STREAMING VERSION: Accumulates tokens from llm_stream into
    ~15-word chunks and sends each to TTS as soon as ready.
    First audio plays within 1-2 seconds.
    
    ✅ FAST: Only loads user + recent messages (cached, ~5ms).
       Skips process_query_and_get_context (embed+search ~500ms)
       since chat() already does that work.
    """
    
    async def stream_chat_with_tts(
        self,
        query: str,
        user_id: str,
        sio: Any,
        sid: str,
        tts_service: Any,
        gender: str = "female"
    ) -> bool:
        """
        Stream AI response token-by-token and send TTS chunks in real-time.
        
        Flow:
        1. Load user + recent messages (FAST, cached)
        2. Start llm_stream — tokens arrive in real-time
        3. Accumulate tokens into ~15-word chunks
        4. Send each chunk to TTS immediately when ready
        """
        try:
            # 1. ✅ FAST context — only cached data, no embedding/search
            user_details, recent_context = await asyncio.gather(
                load_user(user_id),
                get_last_n_messages(user_id, n=10),
            )
            query_context = []  # Stream doesn't need semantic context
            
            if not user_details:
                logger.error(f"❌ User {user_id} not found")
                return False
            
            # 2. Build prompt
            emotion = "neutral"
            if user_details["language"] == "ne":
                prompt = stream_prompt.build_prompt_ne(
                    emotion, query, recent_context, query_context, user_details
                )
            elif user_details["language"] == "hi":
                prompt = stream_prompt.build_prompt_hi(
                    emotion, query, recent_context, query_context, user_details
                )
            else:
                prompt = stream_prompt.build_prompt_en(
                    emotion, query, recent_context, query_context, user_details
                )
            
            # 3. Stream tokens and send TTS chunks in real-time
            logger.info(f"🎤 Starting stream for user {user_id}")
            messages = [{"role": "user", "content": prompt}]
            
            buffer = ""
            chunk_count = 0
            full_response = ""
            
            async for token in llm_stream(messages=messages, model=settings.GROQ_REASONING_MODEL):
                if not token:
                    continue
                    
                buffer += token
                full_response += token
                
                # Check if we have enough words for a chunk
                words = buffer.split()
                if len(words) >= MIN_CHUNK_WORDS:
                    chunk = " ".join(words[:MIN_CHUNK_WORDS])
                    buffer = " ".join(words[MIN_CHUNK_WORDS:])
                    chunk_count += 1
                    
                    logger.info(f"📝 TTS chunk [{chunk_count}]: {chunk[:50]}...")
                    
                    success = await tts_service.stream_to_socket(
                        sio=sio,
                        sid=sid,
                        text=chunk,
                        gender=gender
                    )
                    
                    if not success:
                        logger.warning(f"⚠️ TTS failed for chunk {chunk_count}")
                    
                    # Yield to event loop between chunks
                    await asyncio.sleep(0)
            
            # 4. Flush remaining buffer (whatever is left)
            if buffer.strip():
                chunk_count += 1
                logger.info(f"📝 TTS final chunk [{chunk_count}]: {buffer.strip()[:50]}...")
                
                await tts_service.stream_to_socket(
                    sio=sio,
                    sid=sid,
                    text=buffer.strip(),
                    gender=gender
                )
            
            logger.info(f"✅ Stream completed for {user_id}: {len(full_response)} chars, {chunk_count} TTS chunks")
            return True
            
        except Exception as e:
            logger.error(f"❌ Stream error: {e}", exc_info=True)
            return False



# ==================== CONVENIENCE FUNCTIONS ====================

async def stream_chat_response(
    query: str,
    user_id: str,
    sio: Any,
    sid: str,
    tts_service: Any,
    gender: str = "female"
) -> bool:
    """
    Quick helper for streaming chat with TTS.
    """
    service = StreamService()
    return await service.stream_chat_with_tts(
        query=query,
        user_id=user_id,
        sio=sio,
        sid=sid,
        tts_service=tts_service,
        gender=gender
    )


async def parallel_chat_execution(
    query: str,
    user_id: str,
    sio: Any,
    sid: str,
    tts_service: Any,
    gender: str = "female"
) -> dict:
    """
    Run stream (TTS) and chat (tool execution) truly in parallel.
    
    IMPORTANT: Stream is FULLY INDEPENDENT — it runs as a background task
    and can NEVER be blocked by chat or SQH. Chat returns its result
    immediately without waiting for stream to finish.
    """
    from app.services.chat_service import chat
    
    # ── 1. Launch stream as a fully independent background task ──
    async def _independent_stream():
        """Wrapper that catches all errors so the background task never crashes."""
        try:
            await stream_chat_response(
                query=query,
                user_id=user_id,
                sio=sio,
                sid=sid,
                tts_service=tts_service,
                gender=gender
            )
        except Exception as e:
            logger.error(f"❌ Independent stream failed: {e}", exc_info=True)
    
    stream_bg_task = asyncio.create_task(_independent_stream())
    logger.info(f"🎤 Stream launched as independent background task for {user_id}")
    
    # ── 2. Run chat (PQH → SQH) — returns immediately after PQH ──
    chat_result = None
    try:
        chat_result = await chat(
            query=query,
            user_id=user_id,
            wait_for_execution=False
        )
    except Exception as e:
        logger.error(f"❌ Chat failed: {e}", exc_info=True)
    
    # ── 3. Return chat result immediately — stream continues in background ──
    return {
        "stream_success": not stream_bg_task.done() or not stream_bg_task.cancelled(),
        "chat_result": chat_result
    }