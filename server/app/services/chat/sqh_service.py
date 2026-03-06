"""
SQH Service
Handles Secondary Query Handler logic:
1. Generates Task Plan using LLM
2. Registers tasks with Orchestrator
3. Triggers Execution Engine

✅ UNIFIED: Uses client_tool_executor for desktop, socket for production
✅ Final speech emitted after execution completion using ExecutionState summary
"""

import logging
import json
import asyncio
import re
import time
from typing import List, Dict, Any, Union, Optional, Tuple

from app.agent.execution_gateway import (
    LifecycleMessages,
    Task,
    get_client_executor,
    get_execution_engine,
    get_orchestrator,
    get_server_executor,
    get_task_emitter,
)
from app.models.pqh_response_model import PQHResponse
from app.prompts.sqh_prompt import build_sqh_prompt
from app.ai.providers import llm_chat
from app.config import settings
from .task_summary_speech_service import get_task_summary_speech_service

logger = logging.getLogger(__name__)


def _looks_like_task_object(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    return "tool" in obj and ("task_id" in obj or "inputs" in obj or "input_bindings" in obj)


def _count_task_like_items(candidate: Union[dict, list]) -> int:
    if isinstance(candidate, list):
        return sum(1 for item in candidate if _looks_like_task_object(item))

    tasks = candidate.get("tasks") if isinstance(candidate, dict) else None
    if isinstance(tasks, list):
        return sum(1 for item in tasks if _looks_like_task_object(item))

    if isinstance(candidate, dict) and _looks_like_task_object(candidate):
        return 1

    return 0


def _extract_tasks_and_ack(data: Union[dict, list, None]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    if data is None:
        return [], None

    ack_msg: Optional[str] = None
    tasks_data: List[Dict[str, Any]] = []

    if isinstance(data, list):
        tasks_data = [item for item in data if isinstance(item, dict)]
        return tasks_data, None

    if isinstance(data, dict):
        ack_raw = data.get("acknowledge_answer")
        if isinstance(ack_raw, str):
            ack_msg = ack_raw

        raw_tasks = data.get("tasks")
        if isinstance(raw_tasks, list):
            tasks_data = [item for item in raw_tasks if isinstance(item, dict)]
            return tasks_data, ack_msg

        # Some models return a single task object as top-level JSON.
        if _looks_like_task_object(data):
            return [data], ack_msg

    return [], ack_msg


def _select_best_json_candidate(candidates: List[Union[dict, list]]) -> Union[dict, list, None]:
    if not candidates:
        return None

    scored: List[Tuple[int, int, Union[dict, list]]] = []
    for idx, candidate in enumerate(candidates):
        task_score = _count_task_like_items(candidate)
        scored.append((task_score, idx, candidate))

    # Prefer candidate with most task-like items; on tie prefer the later block.
    best_task_score, _idx, best = max(scored, key=lambda item: (item[0], item[1]))
    if best_task_score > 0:
        return best

    # Otherwise prefer the last dict containing expected SQH keys.
    for candidate in reversed(candidates):
        if isinstance(candidate, dict) and ("tasks" in candidate or "acknowledge_answer" in candidate):
            return candidate

    # Last parsed candidate is usually the most complete block in verbose outputs.
    return candidates[-1]

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
    candidates: List[Union[dict, list]] = []

    # Method 1: Try direct parse (already clean JSON)
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, (dict, list)):
            candidates.append(parsed)
    except json.JSONDecodeError:
        pass

    # Method 2: Parse every fenced block (not only the first).
    for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, flags=re.IGNORECASE):
        block = match.group(1).strip()
        if not block:
            continue
        try:
            parsed = json.loads(block)
            if isinstance(parsed, (dict, list)):
                candidates.append(parsed)
        except json.JSONDecodeError:
            continue

    # Method 3: Bracket-scan fallback from first JSON-looking token.
    first_brace = cleaned.find("{")
    first_bracket = cleaned.find("[")
    start_pos = -1
    if first_brace != -1 and first_bracket != -1:
        start_pos = min(first_brace, first_bracket)
    elif first_brace != -1:
        start_pos = first_brace
    elif first_bracket != -1:
        start_pos = first_bracket

    if start_pos != -1:
        json_candidate = cleaned[start_pos:]
        for end_pos in range(len(json_candidate), 0, -1):
            try:
                parsed = json.loads(json_candidate[:end_pos])
                if isinstance(parsed, (dict, list)):
                    candidates.append(parsed)
                break
            except json.JSONDecodeError:
                continue

    # Method 4: Minor repair for trailing commas.
    fixed = re.sub(r",(\s*[\]}])", r"\1", cleaned)
    try:
        parsed = json.loads(fixed)
        if isinstance(parsed, (dict, list)):
            candidates.append(parsed)
    except json.JSONDecodeError:
        pass

    return _select_best_json_candidate(candidates)


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
        base_prompt = build_sqh_prompt(
            pqh_response,
            user_lang=user_details.get("lang", "en"),
            user_preferences=user_details.get("preferences", {}),
        )

        max_attempts = 1 + max(0, int(getattr(settings, "SQH_PLAN_RETRY_ATTEMPTS", 1)))
        tasks: List[Task] = []
        ack_msg: Optional[str] = None
        last_error: Optional[Exception] = None
        prompt = base_prompt

        for attempt in range(1, max_attempts + 1):
            logger.info("🧠 [SQH] calling LLM... (attempt %d/%d)", attempt, max_attempts)
            raw_response, provider = await llm_chat(messages=[{"role": "user", "content": prompt}])
            logger.info("✅ [SQH] Response received from %s (len=%d)", provider, len(raw_response or ""))

            try:
                if not raw_response:
                    raise ValueError("Empty response from LLM")

                data = extract_json_from_response(raw_response)
                if data is None:
                    raise ValueError("Failed to extract valid JSON from LLM response")

                tasks_data, ack_msg = _extract_tasks_and_ack(data)
                logger.info("SQH response task candidates: %d", len(tasks_data))

                tasks = [Task(**task_data) for task_data in tasks_data]
                if not tasks:
                    raise ValueError("No tasks generated by LLM")

                logger.info(f"📋 [SQH] Parsed {len(tasks)} tasks:")
                for task in tasks:
                    logger.info(f"   - {task.task_id}: {task.tool} ({task.execution_target})")

                if ack_msg:
                    logger.info(f"🎤 [SQH] Acknowledgment: {ack_msg}")

                last_error = None
                break

            except Exception as parse_exc:
                last_error = parse_exc if isinstance(parse_exc, Exception) else Exception(str(parse_exc))
                logger.warning(
                    "⚠️ [SQH] Plan parse/validation failed on attempt %d/%d: %s",
                    attempt,
                    max_attempts,
                    parse_exc,
                )
                if attempt >= max_attempts:
                    break

                # Retry hint makes LLM return strict executable JSON only.
                prompt = (
                    base_prompt
                    + "\n\nIMPORTANT RETRY:\n"
                    + "- Your previous answer could not be executed.\n"
                    + "- Return ONLY one raw JSON object.\n"
                    + "- `tasks` must be a non-empty JSON array of valid task objects.\n"
                    + "- No markdown, no explanation, no analysis.\n"
                )

        if last_error is not None or not tasks:
            raise ValueError(str(last_error or "No tasks generated by LLM"))

        orchestrator = get_orchestrator()
        execution_engine = get_execution_engine()

        # Ensure each SQH call starts from a clean in-memory execution state.
        if execution_engine.is_running(user_id):
            logger.info("🧹 [SQH] Stopping previous execution for user: %s", user_id)
            await execution_engine.stop_execution(user_id)
        await orchestrator.cleanup_user_state(user_id)

        # 4. Register Tasks
        logger.info(f"📝 [SQH] Registering {len(tasks)} tasks with Orchestrator...")
        await orchestrator.register_tasks(user_id, tasks)
        
        # 5. Setup Execution Dependencies
        # ✅ Ensure server executor is set
        if not execution_engine.server_tool_executor:
            logger.info("🔧 [SQH] Injecting server executor...")
            execution_engine.set_server_executor(get_server_executor())
        
        # ✅ UNIFIED: Setup based on environment
        if settings.environment == "DESKTOP":
            # Desktop: inject client tool executor for direct execution
            if not execution_engine.client_tool_executor:
                logger.info("🔧 [SQH] Injecting client tool executor (desktop mode)...")
                execution_engine.set_client_executor(get_client_executor())
        else:
            # Production: inject socket handler for remote emit
            if not execution_engine.socket_handler:
                logger.info("🔧 [SQH] Setting up socket handler (production mode)...")
                client_emitter = get_task_emitter()
                execution_engine.set_client_emitter(client_emitter)
        
        # 6. Trigger Execution Engine - AUTO START
        logger.info(f"⚡ [SQH] Starting execution for {len(tasks)} tasks...")
        await execution_engine.start_execution(user_id)
        
        logger.info(f"✅ [SQH] Execution workflow auto-started for user: {user_id}")
        
        # 7. Emit final spoken summary AFTER execution completes (background task)
        # Keep ack_msg as optional hint for backward compatibility.
        asyncio.create_task(
            _emit_ack_after_completion(
                user_id=user_id,
                message=(ack_msg or ""),
                execution_engine=execution_engine,
            )
        )
        
        return None

    except Exception as e:
        logger.error(f"❌ [SQH] Critical Failure: {e}", exc_info=True)
        raise


async def _emit_ack_after_completion(user_id: str, message: str, execution_engine):
    """
    Wait for execution to complete, THEN emit centralized final TTS summary.
    """
    wait_started = time.perf_counter()
    try:
        completion_event = execution_engine.completion_events.get(user_id)
        if completion_event:
            logger.info(f"⏳ [SQH] Waiting for execution to complete before ack...")
            await asyncio.wait_for(completion_event.wait(), timeout=60)
            wait_ms = (time.perf_counter() - wait_started) * 1000
            logger.info(f"✅ [SQH] Execution done in %.0fms — preparing final summary TTS", wait_ms)

        summary_text = message.strip()
        if settings.FINAL_STATE_SUMMARY_TTS_ENABLED:
            summary_started = time.perf_counter()
            summary_text = await get_task_summary_speech_service().build_summary_text(
                user_id=user_id,
                ack_hint=message,
            )
            logger.info(
                "🧾 [SQH] Summary text built in %.0fms",
                (time.perf_counter() - summary_started) * 1000,
            )

        if not summary_text:
            logger.info("ℹ️ [SQH] Final summary text empty; skipping TTS emit")
            return

        # Emit final summary via socket (works for both desktop and production)
        from app.socket.utils import stream_tts_to_client
        emit_started = time.perf_counter()
        await stream_tts_to_client(summary_text, user_id=user_id)
        logger.info(
            "✅ [SQH] Final summary emitted in %.0fms: %s",
            (time.perf_counter() - emit_started) * 1000,
            summary_text,
        )
    except asyncio.TimeoutError:
        logger.warning(f"⚠️ [SQH] Completion wait timeout — trying summary emit anyway")
        try:
            summary_text = message.strip()
            if settings.FINAL_STATE_SUMMARY_TTS_ENABLED:
                summary_text = await get_task_summary_speech_service().build_summary_text(
                    user_id=user_id,
                    ack_hint=message,
                )

            if summary_text:
                from app.socket.utils import stream_tts_to_client
                await stream_tts_to_client(summary_text, user_id=user_id)
                logger.info(f"✅ [SQH] Timeout-path final summary emitted: {summary_text}")
        except Exception as emit_exc:
            logger.error(f"❌ [SQH] Timeout-path final summary emit failed: {emit_exc}")
    except Exception as e:
        logger.error(f"❌ [SQH] Failed to emit ack after completion: {e}")

