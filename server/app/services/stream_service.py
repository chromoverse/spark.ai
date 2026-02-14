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
        Stream AI response and yield complete sentences.
        
        Chunks at: . ! ? ,
        """
        buffer = ""
        sentence_delimiters = re.compile(r'[.!?,;]')
        
        messages = [{"role": "user", "content": prompt}]
        
        async for chunk in llm_stream(messages):
            buffer += chunk
            
            # Check if we have a sentence delimiter
            if sentence_delimiters.search(buffer):
                # Split on delimiters but keep them
                sentences = sentence_delimiters.split(buffer)
                
                # Yield all complete sentences
                for i in range(len(sentences) - 1):
                    sentence = sentences[i].strip()
                    if sentence:
                        yield sentence
                
                # Keep the incomplete part
                buffer = sentences[-1]
        
        # Yield any remaining text
        if buffer.strip():
            yield buffer.strip()


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