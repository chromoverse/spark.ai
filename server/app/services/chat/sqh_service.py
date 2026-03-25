"""
SQH Service — Secondary Query Handler

1. Build execution plan via LLM
2. Register tasks with Orchestrator
3. Start Execution Engine
4. Emit final TTS summary after completion
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Union

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
from app.prompts.sqh_prompt import build_messages
from app.ai.providers import llm_chat
from app.config import settings
from app.services.interrupt_manager import get_interrupt_manager
from .task_summary_speech_service import get_task_summary_speech_service

logger = logging.getLogger(__name__)
_interrupt = get_interrupt_manager()


# ── JSON extraction ────────────────────────────────────────────────────────────

def _looks_like_task(obj: Any) -> bool:
    return isinstance(obj, dict) and "tool" in obj and (
        "task_id" in obj or "inputs" in obj or "input_bindings" in obj
    )


def _count_tasks(candidate: Union[dict, list]) -> int:
    if isinstance(candidate, list):
        return sum(1 for x in candidate if _looks_like_task(x))
    if isinstance(candidate, dict):
        tasks = candidate.get("tasks")
        if isinstance(tasks, list):
            return sum(1 for x in tasks if _looks_like_task(x))
        if _looks_like_task(candidate):
            return 1
    return 0


def _best_candidate(candidates: List[Union[dict, list]]) -> Union[dict, list, None]:
    if not candidates:
        return None
    scored = [((_count_tasks(c), i), c) for i, c in enumerate(candidates)]
    best_score, best = max(scored, key=lambda x: x[0])
    if best_score[0] > 0:
        return best
    for c in reversed(candidates):
        if isinstance(c, dict) and ("tasks" in c or "acknowledge_answer" in c):
            return c
    return candidates[-1]


def extract_json(response: str) -> Union[dict, list, None]:
    if not response:
        return None
    cleaned = response.strip()
    candidates: List[Union[dict, list]] = []

    # Direct parse
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, (dict, list)):
            candidates.append(parsed)
    except json.JSONDecodeError:
        pass

    # Fenced blocks
    for m in re.finditer(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE):
        block = m.group(1).strip()
        try:
            parsed = json.loads(block)
            if isinstance(parsed, (dict, list)):
                candidates.append(parsed)
        except json.JSONDecodeError:
            pass

    # Bracket scan
    first = min(
        (cleaned.find(c) for c in "{[" if cleaned.find(c) != -1),
        default=-1,
    )
    if first != -1:
        fragment = cleaned[first:]
        for end in range(len(fragment), 0, -1):
            try:
                parsed = json.loads(fragment[:end])
                if isinstance(parsed, (dict, list)):
                    candidates.append(parsed)
                break
            except json.JSONDecodeError:
                pass

    # Trailing-comma repair
    fixed = re.sub(r",(\s*[\]}])", r"\1", cleaned)
    try:
        parsed = json.loads(fixed)
        if isinstance(parsed, (dict, list)):
            candidates.append(parsed)
    except json.JSONDecodeError:
        pass

    return _best_candidate(candidates)


def _unpack(data: Union[dict, list, None]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    if data is None:
        return [], None
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)], None
    if isinstance(data, dict):
        ack  = data.get("acknowledge_answer") if isinstance(data.get("acknowledge_answer"), str) else None
        raw  = data.get("tasks")
        if isinstance(raw, list):
            return [x for x in raw if isinstance(x, dict)], ack
        if _looks_like_task(data):
            return [data], ack
    return [], None


# ── Main service ───────────────────────────────────────────────────────────────

async def process_sqh(pqh_response: PQHResponse, user_details: Dict[str, Any]) -> None:
    user_id  = str(user_details.get("_id", "guest"))
    user_lang = user_details.get("lang", "en")
    original_query = pqh_response.cognitive_state.user_query or ""

    try:
        messages     = build_messages(
            pqh_response=pqh_response,
            user_lang=user_details.get("lang", "en"),
            user_preferences=user_details.get("preferences", {}),
        )
        retry_limit  = 1 + max(0, int(getattr(settings, "SQH_PLAN_RETRY_ATTEMPTS", 1)))
        tasks:  List[Task]   = []
        ack:    Optional[str] = None
        last_error: Optional[Exception] = None

        for attempt in range(1, retry_limit + 1):
            raw, _ = await llm_chat(messages=messages)

            try:
                if not raw:
                    raise ValueError("empty LLM response")

                data = extract_json(raw)
                if data is None:
                    raise ValueError("no valid JSON in response")

                tasks_data, ack = _unpack(data)
                tasks = [Task(**t) for t in tasks_data]

                if not tasks:
                    raise ValueError("no tasks in plan")

                last_error = None
                break

            except Exception as exc:
                last_error = exc
                logger.warning("[SQH] attempt %d/%d failed: %s", attempt, retry_limit, exc)
                if attempt >= retry_limit:
                    break
                # Append retry instruction to last user message
                messages = messages[:-1] + [{
                    "role": "user",
                    "content": (
                        messages[-1]["content"]
                        + "\n\nRETRY: Previous output was invalid. "
                        "Return ONLY raw JSON. `tasks` must be a non-empty array. "
                        "No markdown, no explanation."
                    ),
                }]

        if last_error or not tasks:
            raise ValueError(str(last_error or "no tasks generated"))

        # ── Register + start execution ────────────────────────────────────
        orchestrator    = get_orchestrator()
        execution_engine = get_execution_engine()

        if execution_engine.is_running(user_id):
            await execution_engine.stop_execution(user_id)
        await orchestrator.cleanup_user_state(user_id)

        await orchestrator.register_tasks(user_id, tasks)

        if not execution_engine.server_tool_executor:
            execution_engine.set_server_executor(get_server_executor())

        if settings.environment == "DESKTOP":
            if not execution_engine.client_tool_executor:
                execution_engine.set_client_executor(get_client_executor())
        else:
            if not execution_engine.socket_handler:
                execution_engine.set_client_emitter(get_task_emitter())

        await execution_engine.start_execution(user_id)

        # Emit TTS summary after execution finishes
        asyncio.create_task(_emit_summary(user_id, ack or "", execution_engine, original_query, user_lang))

    except Exception as exc:
        logger.error("[SQH] critical failure user=%s: %s", user_id, exc, exc_info=True)
        raise


# ── Post-execution TTS summary ─────────────────────────────────────────────────

async def _emit_summary(
    user_id: str,
    ack_hint: str,
    execution_engine: Any,
    original_query: str = "",
    user_lang: str = "en",
) -> None:
    """Wait for execution to complete, then emit final TTS summary (only when meaningful)."""
    try:
        event = execution_engine.completion_events.get(user_id)
        if event:
            await asyncio.wait_for(event.wait(), timeout=60)
    except asyncio.TimeoutError:
        logger.warning("[SQH] completion wait timed out for user=%s — emitting anyway", user_id)
    except Exception as exc:
        logger.error("[SQH] completion wait error user=%s: %s", user_id, exc)

    # Skip if user already interrupted (started speaking again)
    if _interrupt.is_set(user_id):
        logger.info("⏭️ Skipping summary TTS — user %s interrupted", user_id)
        return

    try:
        # Smart gate: decide if summary is worth speaking
        orchestrator = get_orchestrator()
        snapshot_raw = await orchestrator.build_execution_speech_snapshot(user_id=user_id)
        if not _should_speak(snapshot_raw, original_query):
            logger.info("⏭️ Skipping summary TTS — no tool needs summary for user=%s", user_id)
            return

        summary = ack_hint.strip()
        if settings.FINAL_STATE_SUMMARY_TTS_ENABLED:
            summary = await get_task_summary_speech_service().build_summary_text(
                user_id=user_id,
                ack_hint=ack_hint,
                original_query=original_query,
                user_lang=user_lang,
            )

        if not summary:
            return

        # Final interrupt check before speaking
        if _interrupt.is_set(user_id):
            logger.info("⏭️ Skipping summary TTS (post-build) — user %s interrupted", user_id)
            return

        from app.socket.utils import stream_tts_to_client
        await stream_tts_to_client(summary, user_id=user_id)

    except Exception as exc:
        logger.error("[SQH] summary emit failed user=%s: %s", user_id, exc)


# ── Smart gate: should we speak the summary? ────────────────────────────────────────


def _tool_wants_summary_tts(tool_name: str) -> bool:
    """Check the tool registry's summary_tts flag for a given tool."""
    from app.plugins.tools.registry_loader import get_tool_registry
    registry = get_tool_registry()
    meta = registry.get_tool(tool_name)
    if meta is None:
        return False
    return bool(meta.metadata.get("summary_tts", False))


def _should_speak(snapshot_raw: Dict[str, Any], original_query: str = "") -> bool:
    """
    Registry-driven gate: speak only when a tool's summary_tts flag is true,
    or when there are failures. No hardcoded tool lists.

    No LLM call — pure dict + registry inspection, ~0 latency.
    """
    summary = snapshot_raw.get("summary", {})
    tasks = snapshot_raw.get("tasks", [])
    failed    = summary.get("failed", 0)

    logger.info("[_should_speak] summary=%s  tasks_count=%d", summary, len(tasks))

    # Always speak if there's a failure
    if failed > 0:
        logger.info("[_should_speak] speaking — %d failure(s)", failed)
        return True

    # Check if ANY completed tool has summary_tts=true in the registry
    for task in tasks:
        status = task.get("status")
        tool = str(task.get("tool") or task.get("task", {}).get("tool", "")).strip()
        if status != "completed":
            logger.info("[_should_speak] skip task %s status=%s", tool, status)
            continue
        wants = _tool_wants_summary_tts(tool) if tool else False
        logger.info("[_should_speak] tool=%s  summary_tts=%s", tool, wants)
        if wants:
            logger.info("[_should_speak] speaking — tool '%s' has summary_tts=true", tool)
            return True

    # No tool needs summary TTS → skip
    logger.info("[_should_speak] silent — no tool needs summary TTS")
    return False