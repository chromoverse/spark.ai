"""
Streaming Chat Service - Real-time AI responses with TTS integration

NATURAL VERSION: Removes artificial delays for smooth, natural-sounding speech.
"""
import logging
import asyncio
import re
from typing import Optional, AsyncGenerator, Any
from app.ai.providers import llm_stream
from app.cache import load_user, get_last_n_messages, process_query_and_get_context
from app.prompts import stream_prompt
from app.config import settings

logger = logging.getLogger(__name__)


class StreamService:
    """
    Handles real-time streaming responses with intelligent sentence chunking.
    
    NATURAL VERSION: No artificial delays - let audio flow naturally!
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
        Stream AI response and convert to audio in real-time.
        
        NATURAL: No delays - streams flow as fast as they're generated.
        Frontend handles timing to prevent overlap.
        """
        try:
            # Load user details
            user_details = await load_user(user_id)
            if not user_details:
                logger.error(f"❌ User {user_id} not found")
                return False
            
            # Get context
            recent_context = await get_last_n_messages(user_id, n=10)
            query_context, _ = await process_query_and_get_context(user_id, query)
            
            # Build streaming prompt
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
            
            logger.info(f"🎤 Starting stream for user {user_id}")
            
            # Start streaming - NO DELAYS
            async for sentence in self._stream_with_sentence_chunking(prompt):
                logger.info(f"📝 Sending sentence to TTS: {sentence[:50]}...")
                
                # Send to TTS service - let it send immediately
                success = await tts_service.stream_to_socket(
                    sio=sio,
                    sid=sid,
                    text=sentence,
                    gender=gender
                )
                
                if not success:
                    logger.warning(f"⚠️ TTS failed for sentence: {sentence[:30]}...")
                    continue
                
                # NO DELAY - continue immediately to next sentence
                # Natural speech timing comes from:
                # 1. TTS generation time (~1-2 seconds per sentence)
                # 2. Frontend smart timing (only delays if needed)
            
            logger.info(f"✅ Stream completed for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Stream error: {e}", exc_info=True)
            return False
    
    async def _stream_with_sentence_chunking(
        self,
        prompt: str
    ) -> AsyncGenerator[str, None]:
        """
        Stream AI response and yield chunks suitable for TTS.

        Rules:
        - Only split at sentence-ending punctuation:  . ! ?
        - Collapse repeated punctuation (e.g. "..." or "!!!" count
          as a single boundary).
        - Keep delimiters attached to the preceding text so TTS can
          use the punctuation for intonation.
        - Enforce a minimum chunk length (MIN_CHUNK_LENGTH chars).
          If the current split is too short, merge it into the next
          chunk instead of yielding a tiny fragment.
        """
        MIN_CHUNK_LENGTH = 40  # characters — prevents tiny TTS calls

        # Matches one or more sentence-ending punctuation chars,
        # optionally followed by a closing quote/bracket.
        # e.g.  .  ...  !!  ?!  ."  ?)
        _split_re = re.compile(r'([.!?]+["\')»\]]*)')

        buffer = ""
        carry = ""  # short fragment waiting to be merged

        messages = [{"role": "user", "content": prompt}]

        async for chunk in llm_stream(messages, model=settings.GROQ_REASONING_MODEL):
            buffer += chunk

            # Try to split on sentence-ending punctuation
            parts = _split_re.split(buffer)

            # _split_re.split produces:
            #   [text_before, delimiter, text_after, delimiter, …]
            # We reconstruct "sentence + delimiter" pairs.
            i = 0
            while i < len(parts) - 2:
                sentence = parts[i] + parts[i + 1]  # text + delimiter
                sentence = (carry + " " + sentence).strip() if carry else sentence.strip()
                carry = ""

                if len(sentence) < MIN_CHUNK_LENGTH:
                    # Too short — carry forward and merge with next
                    carry = sentence
                else:
                    yield sentence

                i += 2

            # Whatever is left is the new incomplete buffer
            buffer = parts[-1] if parts else ""

        # Flush remaining buffer + carry
        final = ((carry + " " if carry else "") + buffer).strip()
        if final:
            yield final



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
    Run both stream (TTS) and normal chat (tool execution) in parallel.
    """
    from app.services.chat_service import chat
    
    # Run both in parallel
    stream_task = stream_chat_response(
        query=query,
        user_id=user_id,
        sio=sio,
        sid=sid,
        tts_service=tts_service,
        gender=gender
    )
    
    chat_task = chat(
        query=query,
        user_id=user_id,
        wait_for_execution=False
    )
    
    # Execute in parallel
    stream_result, chat_result = await asyncio.gather(
        stream_task,
        chat_task,
        return_exceptions=True
    )
    
    if isinstance(stream_result, Exception):
        logger.error(f"Stream failed: {stream_result}")
    
    if isinstance(chat_result, Exception):
        logger.error(f"Chat failed: {chat_result}")
    
    return {
        "stream_success": not isinstance(stream_result, Exception),
        "chat_result": chat_result if not isinstance(chat_result, Exception) else None
    }