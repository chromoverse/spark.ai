"""
Streaming Chat Service - Real-time AI responses with TTS integration

STREAMING VERSION: Uses llm_stream for real-time token streaming.
Accumulates tokens and splits at natural sentence boundaries before sending to TTS.
TTS starts speaking within 1-2 seconds instead of waiting for full response.
"""
import logging
import re
import asyncio
from typing import Optional, List, Any, Tuple
from app.ai.providers import llm_stream, llm_chat
from app.cache import load_user, get_last_n_messages, process_query_and_get_context
from app.prompts import stream_prompt
from app.config import settings

logger = logging.getLogger(__name__)

# ── Chunking thresholds ─────────────────────────────────────────────────────
# MIN: don't flush until at least this many words (avoids tiny fragments)
MIN_CHUNK_WORDS = 5
# SOFT: try to flush at sentence boundaries once we reach this many words
SOFT_CHUNK_WORDS = 12
# MAX: force-flush even without a boundary to prevent long silences
MAX_CHUNK_WORDS = 30

# Sentence-ending punctuation that signals a strong break
# Negative lookbehind (?<!\.) ensures "..." (ellipsis) is NOT treated as a period
_SENTENCE_END_RE = re.compile(r'(?<!\.)(?<!…)[.!?][""\')]?\s*$')
# Weaker break points (comma, semicolon, colon, em-dash) — only used
# when the buffer already has enough words
_CLAUSE_BREAK_RE = re.compile(r'[,;:\u2014]\s*$')


def _find_split_point(buffer: str) -> int:
    """
    Find the best point to split a buffer for natural-sounding TTS.
    
    Returns the character index to split at (exclusive), or -1 if no
    good split point is found yet.
    
    Priority:
        1. Sentence end (.!?) if buffer has >= MIN_CHUNK_WORDS
        2. Clause break (,;:—) if buffer has >= SOFT_CHUNK_WORDS
        3. -1 (don't split yet)
    """
    words = buffer.split()
    word_count = len(words)
    
    if word_count < MIN_CHUNK_WORDS:
        return -1
    
    # Force-flush at MAX regardless
    if word_count >= MAX_CHUNK_WORDS:
        # Even here, try to find the last sentence-end before MAX
        # Search backwards for a good break
        for pattern in (_SENTENCE_END_RE, _CLAUSE_BREAK_RE):
            # Search from the end of the buffer backwards
            matches = list(pattern.finditer(buffer))
            if matches:
                last_match = matches[-1]
                # Only use if it produces a chunk with >= MIN_CHUNK_WORDS
                candidate = buffer[:last_match.end()]
                if len(candidate.split()) >= MIN_CHUNK_WORDS:
                    return last_match.end()
        # No break found — force split at the last space before MAX words
        forced = " ".join(words[:MAX_CHUNK_WORDS])
        return len(forced)
    
    # Sentence end — always a good break after MIN words
    match = _SENTENCE_END_RE.search(buffer)
    if match and len(buffer[:match.end()].split()) >= MIN_CHUNK_WORDS:
        return match.end()
    
    # Clause break — acceptable only after SOFT words
    if word_count >= SOFT_CHUNK_WORDS:
        matches = list(_CLAUSE_BREAK_RE.finditer(buffer))
        if matches:
            last_match = matches[-1]
            candidate = buffer[:last_match.end()]
            if len(candidate.split()) >= MIN_CHUNK_WORDS:
                return last_match.end()
    
    return -1


class StreamService:
    """
    Handles real-time AI responses with TTS.
    
    STREAMING VERSION: Accumulates tokens from llm_stream and splits
    at natural sentence/clause boundaries for human-sounding speech.
    First audio plays within 1-2 seconds.
    
    ✅ FAST: Loads user + recent messages + semantic context ALL IN PARALLEL.
       Embedding + LanceDB search runs concurrently with cached lookups,
       so total latency ≈ max(cache, embed) instead of cache + embed.
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
        3. Accumulate tokens, split at sentence/clause boundaries
        4. Send each chunk to TTS immediately when ready
        """
        try:
            # 1. ✅ FAST context — ALL THREE run in parallel
            user_details, recent_context= await asyncio.gather(
                load_user(user_id),
                get_last_n_messages(user_id, n=10),
            )

            query_context = []
            
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
            
            # 3. Generate response and send TTS
            logger.info(f"🎤 Starting {'chat' if settings.groq_mode else 'stream'} for user {user_id}")
            messages = [{"role": "user", "content": prompt}]
            
            if settings.groq_mode:
                # ── GROQ MODE: instant full response → single TTS call ──
                # No token streaming — get the complete response at once,
                # then send the entire text to Groq TTS as one chunk.
                llm_result = await llm_chat(
                    messages=messages,
                    # model=settings.GROQ_REASONING_MODEL,
                )
                full_response = (llm_result[0] or "").strip()
                
                if full_response:
                    logger.info(f"📝 Groq chat response: {len(full_response)} chars")
                    
                    success = await tts_service.stream_to_socket(
                        sio=sio,
                        sid=sid,
                        text=full_response,
                        gender=gender,
                    )
                    if not success:
                        logger.warning("⚠️ TTS failed for Groq response")
                else:
                    logger.warning("⚠️ Groq chat returned empty response")
                    
            else:
                # ── DEFAULT MODE: token streaming + sentence-boundary TTS ──
                buffer = ""
                chunk_count = 0
                full_response = ""
                
                async for token in llm_stream(messages=messages):
                    if not token:
                        continue
                        
                    buffer += token
                    full_response += token
                    
                    # Try to find a natural split point
                    split_at = _find_split_point(buffer)
                    if split_at > 0:
                        chunk = buffer[:split_at].strip()
                        buffer = buffer[split_at:].lstrip()
                        
                        if chunk:
                            chunk_count += 1
                            logger.info(f"📝 TTS chunk [{chunk_count}]: {chunk[:60]}...")
                            
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
                
                # Flush remaining buffer (whatever is left)
                if buffer.strip():
                    chunk_count += 1
                    logger.info(f"📝 TTS final chunk [{chunk_count}]: {buffer.strip()[:50]}...")
                    
                    await tts_service.stream_to_socket(
                        sio=sio,
                        sid=sid,
                        text=buffer.strip(),
                        gender=gender
                    )
            
            logger.info(f"✅ {'Chat' if settings.groq_mode else 'Stream'} completed for {user_id}: {len(full_response)} chars")
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