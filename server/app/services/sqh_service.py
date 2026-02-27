"""
SQH Service
Handles Secondary Query Handler logic:
1. Generates Task Plan using LLM
2. Registers tasks with Orchestrator
3. Triggers Execution Engine

✅ UNIFIED: Uses client_tool_executor for desktop, socket for production
✅ Ack emitted IMMEDIATELY (no waiting for execution)
"""

import logging
import json
import asyncio
import re
from typing import List, Dict, Any, Union

from app.agent.core.models import LifecycleMessages, Task
from app.models.pqh_response_model import PQHResponse
from app.prompts.sqh_prompt import build_sqh_prompt
from app.ai.providers import llm_chat
from app.agent.core.orchestrator import get_orchestrator
from app.agent.core.execution_engine import get_execution_engine
from app.agent.core.server_executor import get_server_executor

logger = logging.getLogger(__name__)

def extract_json_from_response(response: str) -> Union[dict, list, None]:
    """
    Smart JSON extraction from LLM responses.
    
    Handles:
    - Plain JSON: { ... } or [ ... ]
    - Markdown code blocks: ```json ... ``` or ``` ... ```
    - Explanatory text before/after JSON
    - Partial JSON with trailing text
    - Nested structures
    
    Returns:
        Parsed JSON (dict or list) or None if parsing fails
    """
    if not response:
        return None
    
    cleaned = response.strip()
    
    # Method 1: Try direct parse (already clean JSON)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    
    # Method 2: Extract from ```json ... ``` blocks
    json_match = re.search(r'```json\s*([\s\S]*?)\s*```', cleaned)
    if json_match:
        try:
            return json.loads(json_match.group(1).strip())
        except json.JSONDecodeError:
            pass
    
    # Method 3: Extract from plain ``` ... ``` blocks
    json_match = re.search(r'```\s*([\s\S]*?)\s*```', cleaned)
    if json_match:
        try:
            return json.loads(json_match.group(1).strip())
        except json.JSONDecodeError:
            pass
    
    # Method 4: Find first { or [ and try to match brackets to extract full JSON
    # This handles explanatory text before the JSON
    first_brace = cleaned.find('{')
    first_bracket = cleaned.find('[')
    
    start_pos = -1
    start_char = ''
    
    if first_brace != -1 and first_bracket != -1:
        start_pos = min(first_brace, first_bracket)
        start_char = cleaned[start_pos]
    elif first_brace != -1:
        start_pos = first_brace
        start_char = '{'
    elif first_bracket != -1:
        start_pos = first_bracket
        start_char = '['
    
    if start_pos != -1:
        # Use a bracket-matching approach to find the complete JSON
        json_candidate = cleaned[start_pos:]
        
        # Try to parse from start_pos to find the complete JSON
        for end_pos in range(len(json_candidate), 0, -1):
            try:
                result = json.loads(json_candidate[:end_pos])
                return result
            except json.JSONDecodeError:
                continue
    
    # Method 5: Try to fix common JSON issues (trailing commas, single quotes, etc.)
    # Remove trailing commas before } or ]
    fixed = re.sub(r',(\s*[\]}])', r'\1', cleaned)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass
    
    # Method 6: Last resort - try to find and extract any valid JSON object/array
    # Look for any {...} or [...] pattern that might be valid
    all_matches = re.findall(r'(\{[\s\S]*\}|[[\s\S]*\])', cleaned)
    for match in all_matches:
        try:
            result = json.loads(match)
            # Only return if it has expected keys (for task plans)
            if isinstance(result, dict) and ('tasks' in result or 'acknowledge_answer' in result):
                return result
            elif isinstance(result, list):
                return result
        except json.JSONDecodeError:
            continue
    
    return None


async def process_sqh(
    pqh_response: PQHResponse,
    user_details: Dict[str, Any]
) -> None:
    """
    Process SQH in background - AUTO INITIALIZES and STARTS EXECUTION:
    - Generate Plan
    - Register Tasks
    - Trigger Execution Engine (automatically, no waiting)
    
    ✅ UPDATED: Emits ack immediately, unified engine handles the rest
    
    Raises:
        ValueError: If LLM response is invalid or parsing fails
        RuntimeError: If task generation fails
    """
    user_id = user_details.get("_id", "guest")
    if not isinstance(user_id, str):
        user_id = str(user_id)

    logger.info(f"🚀 [SQH] Starting background task generation for user: {user_id}")

    try:
        # 1. Build Prompt
        prompt = build_sqh_prompt(pqh_response, user_lang=user_details.get("lang", "en"), user_preferences=user_details.get("preferences", {}))
        
        # 2. Call AI via unified provider system
        messages = [{"role": "user", "content": prompt}]
        
        logger.info("🧠 [SQH] calling LLM...")
        raw_response, provider = await llm_chat(messages=messages)
        
        logger.info(f"✅ [SQH] Response {raw_response} received from {provider}")

        if not raw_response:
            error_msg = "Empty response from LLM"
            logger.error(f"❌ [SQH] {error_msg}")
            raise ValueError(error_msg)
        
        # 3. Parse Response using smart extraction
        try:
            # Use smart JSON extraction that handles all LLM response formats
            data = extract_json_from_response(raw_response)
            
            if data is None:
                error_msg = "Failed to extract valid JSON from LLM response"
                logger.error(f"❌ [SQH] {error_msg}")
                logger.debug(f"Raw response: {raw_response}")
                raise ValueError(error_msg)
            
            tasks_data = []
            ack_msg = None
            
            if isinstance(data, list):
                tasks_data = data
            elif isinstance(data, dict):
                tasks_data = data.get("tasks", [])
                ack_msg = data.get("acknowledge_answer")
            else:
                error_msg = f"Invalid JSON format: {type(data)}"
                logger.error(f"❌ [SQH] {error_msg}")
                raise ValueError(error_msg)
            
            logger.info(f"SQH response:\n{json.dumps(tasks_data, indent=2)}")
            tasks = [Task(**task_data) for task_data in tasks_data]

            if ack_msg:
                logger.info(f"🎤 [SQH] Acknowledgment: {ack_msg}")
            
            if not tasks:
                error_msg = "No tasks generated by LLM"
                logger.warning(f"⚠️ [SQH] {error_msg}")
                raise ValueError(error_msg)
            
            logger.info(f"📋 [SQH] Parsed {len(tasks)} tasks:")
            for task in tasks:
                logger.info(f"   - {task.task_id}: {task.tool} ({task.execution_target})")

        except json.JSONDecodeError as e:
            error_msg = f"JSON Parse Error: {e}"
            logger.error(f"❌ [SQH] {error_msg}")
            logger.debug(f"Raw response: {raw_response}")
            raise ValueError(error_msg) from e
        except ValueError:
            raise
        except Exception as e:
            error_msg = f"Task Validation Error: {e}"
            logger.error(f"❌ [SQH] {error_msg}")
            raise RuntimeError(error_msg) from e

        # 4. Register Tasks
        logger.info(f"📝 [SQH] Registering {len(tasks)} tasks with Orchestrator...")
        orchestrator = get_orchestrator()
        await orchestrator.register_tasks(user_id, tasks)
        
        # 5. Setup Execution Dependencies
        execution_engine = get_execution_engine()
        
        # ✅ Ensure server executor is set
        if not execution_engine.server_tool_executor:
            logger.info("🔧 [SQH] Injecting server executor...")
            execution_engine.set_server_executor(get_server_executor())
        
        # ✅ UNIFIED: Setup based on environment
        from app.config import settings
        
        if settings.environment == "desktop":
            # Desktop: inject client tool executor for direct execution
            if not execution_engine.client_tool_executor:
                logger.info("🔧 [SQH] Injecting client tool executor (desktop mode)...")
                from app.agent.core.client_executor import get_client_executor
                execution_engine.set_client_executor(get_client_executor())
        else:
            # Production: inject socket handler for remote emit
            if not execution_engine.socket_handler:
                logger.info("🔧 [SQH] Setting up socket handler (production mode)...")
                from app.agent.core.task_emitter import get_task_emitter
                client_emitter = get_task_emitter()
                execution_engine.set_client_emitter(client_emitter)
        
        # 6. Trigger Execution Engine - AUTO START
        logger.info(f"⚡ [SQH] Starting execution for {len(tasks)} tasks...")
        await execution_engine.start_execution(user_id)
        
        logger.info(f"✅ [SQH] Execution workflow auto-started for user: {user_id}")
        
        # 7. ✅ Emit ack AFTER execution completes (background task)
        # Ack is past-tense ("Opened YouTube Sir") — only makes sense after tasks finish
        if ack_msg:
            asyncio.create_task(_emit_ack_after_completion(
                user_id, ack_msg, execution_engine
            ))
        
        return None

    except Exception as e:
        logger.error(f"❌ [SQH] Critical Failure: {e}", exc_info=True)
        raise


async def _emit_ack_after_completion(user_id: str, message: str, execution_engine):
    """
    Wait for execution to complete, THEN emit ack TTS.
    
    ✅ This now works reliably because the unified engine marks completion
    on the SAME orchestrator — completion_event always fires.
    """
    try:
        completion_event = execution_engine.completion_events.get(user_id)
        if completion_event:
            logger.info(f"⏳ [SQH] Waiting for execution to complete before ack...")
            await asyncio.wait_for(completion_event.wait(), timeout=60)
            logger.info(f"✅ [SQH] Execution done — now emitting ack TTS: {message}")
        
        # Emit ack via socket (works for both desktop and production)
        from app.socket.utils import stream_tts_to_client
        await stream_tts_to_client(message, user_id=user_id)
        
        logger.info(f"✅ [SQH] Ack emitted: {message}")
    except asyncio.TimeoutError:
        logger.warning(f"⚠️ [SQH] Ack timeout — emitting anyway: {message}")
        from app.socket.utils import stream_tts_to_client
        await stream_tts_to_client(message, user_id=user_id)
    except Exception as e:
        logger.error(f"❌ [SQH] Failed to emit ack after completion: {e}")