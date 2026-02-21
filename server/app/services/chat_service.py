from app.utils import  clean_pqh_response
from app.models.pqh_response_model import CognitiveState, PQHResponse
from app.cache import load_user 
from app.ai.providers import llm_chat
from app.prompts import pqh_prompt
from app.services.sqh_service import process_sqh
import asyncio
import logging

logger = logging.getLogger(__name__)

async def chat(
    query: str,
    user_id: str = "guest",
    wait_for_execution: bool = False,  # ✅ NEW: Option to wait for tasks
    execution_timeout: float = 30.0     # ✅ NEW: Timeout for execution
) -> PQHResponse:
    """
    Main entry point for the chat service as PQH - Primary Query Handler.
    
    Args:
        query: User's message
        user_id: User identifier
        model_name: Optional model name for OpenRouter fallback
        wait_for_execution: If True, waits for task execution to complete (default: False)
        execution_timeout: Max seconds to wait for execution (default: 30)
    
    Returns:
        clean_pqh_response.PQHResponse: Structured response from the AI
        
    Note:
        In production (web server), keep wait_for_execution=False for async behavior.
        In testing/CLI, set wait_for_execution=True to ensure tasks complete.
    """
    if not query or not query.strip():
        return _create_error_response("Empty query received", "neutral")
    
    try:
        # --- Load User Details ---
        user_details = await load_user(user_id)

        if not user_details:
            logger.error(f"❌ Could not load user details for {user_id}")
            return _create_error_response(
                "User not found. Please log in again.",
                "neutral",
                query
            )
        print("BYPASS 1 -  USER from redis",user_details)

        # ---  Emotion Detection (placeholder) ---
        emotion = "neutral"

        # --- Build Prompt ---
        prompt = pqh_prompt.build_prompt(query)
        
        # --- Step 5: Call AI with Smart Fallback ---
        messages = [{"role": "user", "content": prompt}]
        
        raw_response, provider_used = await llm_chat(
            messages=messages,
        )

        print("BYPASS  -  raw response", raw_response)
        
        print(f"✅ Response received from {provider_used}")
        
        if not raw_response:
            return clean_pqh_response._create_error_pqh_response("Empty AI response", emotion)
        
        # --- Step 6: Clean and Return Response ---
        cleaned_response = clean_pqh_response.clean_pqh_response(raw_response, emotion)

        
        # # Add ai response to Redis asynchronously
        # asyncio.create_task(
        #     redis_add_message(
        #         user_id=user_id,
        #         role="ai",
        #         content=cleaned_response.cognitive_state.answer_english
        #     )
        # )
        # # Add chat message to MongoDB asynchronously
        # asyncio.create_task(
        #  add_chat_message_to_mongo(
        #     ChatController(
        #         user_id=user_id,
        #         user_query=query,
        #         ai_response=cleaned_response.cognitive_state.answer_english
        #     )
        # ))

        # --- Step 7: Trigger SQH in Background (if tools needed) ---
        if cleaned_response.requested_tool and len(cleaned_response.requested_tool) > 0:
            logger.info("🔧 Tools requested by PQH. Triggering SQH in background...")
            
            # ✅ NEW: Option to wait for execution completion
            if wait_for_execution:
                await _execute_and_wait(
                    cleaned_response=cleaned_response,
                    user_details=user_details,
                    user_id=user_id,
                    timeout=execution_timeout
                )
            else:
                # Original behavior: fire-and-forget
                asyncio.create_task(
                    process_sqh(cleaned_response, user_details)
                )
        
        return cleaned_response
    
    except Exception as e:
        logger.error(f"❌ Chat service error: {e}", exc_info=True)
        error_message = str(e) if str(e) else "Sorry, I'm having trouble processing your request."
        return _create_error_response(error_message, "neutral", query)


async def _execute_and_wait(
    cleaned_response: PQHResponse,
    user_details: dict,
    user_id: str,
    timeout: float = 30.0
) -> None:
    """
    ✅ NEW: Execute tasks and wait for completion with timeout
    
    This is used when wait_for_execution=True in chat()
    Ensures all tasks complete before returning
    
    Args:
        cleaned_response: PQH response with tool requests
        user_details: User information
        user_id: User identifier
        timeout: Max seconds to wait
    """
    from app.agent.core.execution_engine import get_execution_engine
    
    try:
        logger.info(f"⏳ Starting execution and waiting (timeout: {timeout}s)...")
        
        # Start execution and get the task
        execution_task = await process_sqh(cleaned_response, user_details)
        
        # Wait for completion with timeout
        engine = get_execution_engine()
        success = await engine.wait_for_completion(user_id, timeout=timeout)
        
        if success:
            logger.info(f"✅ Task execution completed for user: {user_id}")
        else:
            logger.warning(f"⏰ Task execution timed out after {timeout}s for user: {user_id}")
            
    except asyncio.TimeoutError:
        logger.error(f"❌ Execution timeout after {timeout}s for user: {user_id}")
    except Exception as e:
        logger.error(f"❌ Error during task execution: {e}", exc_info=True)

    

def _create_error_response(message: str, emotion: str, query: str = "") -> PQHResponse:
    """Helper to create fallback error responses with all required fields."""
   
    return PQHResponse(
       request_id="error_response",
       cognitive_state=CognitiveState(
              user_query=query,
              emotion=emotion,
              thought_process="Error occurred while processing the request.",
              answer=message,
              answer_english=message
         ),
         requested_tool=[]
    )