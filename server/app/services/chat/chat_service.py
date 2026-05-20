"""
PQH — Primary Query Handler (chat_service.py)

Messages structure:
  [system]      — tool decision rules + available tools  (static, Groq caches it)
  [user/asst]*  — real recent conversation turns
  [user]        — the raw query, nothing else
"""

from __future__ import annotations

import asyncio
import logging

from app.utils import clean_pqh_response
from app.models.pqh_response_model import CognitiveState, PQHResponse
from app.cache import load_user, get_last_n_messages
from app.ai.providers import llm_chat, routed_chat
from app.prompts import pqh_prompt_v2 as pqh_prompt
from .sqh_service import process_sqh
from .clarification_service import request_clarification
from app.agent.runtime import is_meta_query, try_handle_meta_query

logger = logging.getLogger(__name__)

_RECENT_TURNS = 5


async def _run_sqh_background(cleaned_response: PQHResponse, user_details: dict, user_id: str) -> None:
    try:
        await process_sqh(cleaned_response, user_details)
    except Exception as exc:
        logger.error("[SQH] background failure user=%s: %s", user_id, exc, exc_info=True)


async def _resolve_clarification(
    query: str,
    pqh_response: PQHResponse,
    user_id: str,
    user_details: dict,
) -> PQHResponse | None:
    """
    Ask the user for missing details and fold the answer back into the PQH response.

    Returns:
        - PQHResponse with enriched cognitive_state.user_query on success
        - None on timeout/cancel — caller will surface a graceful fallback
    """
    try:
        answer = await request_clarification(
            user_id=user_id,
            original_query=query,
            pqh_response=pqh_response,
            user_details=user_details,
        )
    except asyncio.CancelledError:
        logger.info("clarification cancelled user=%s", user_id)
        return None
    except Exception as exc:
        logger.error("clarification flow failed user=%s: %s", user_id, exc, exc_info=True)
        return None

    if not answer:
        return None

    # Enrich the query so SQH plans with both the original ask and the new detail.
    enriched = f"{query}\n[user clarification]: {answer.strip()}"
    pqh_response.cognitive_state.user_query = enriched
    pqh_response.needs_clarification = False
    logger.info("clarification resolved user=%s answer=%r", user_id, answer[:80])
    return pqh_response


def _build_messages(
    query: str,
    recent_context: list[dict],
) -> list[dict[str, str]]:
    """
    Proper multi-turn messages for PQH.

      [system]     — tool decision engine rules + available tools (static)
      [user/asst]* — real recent turns so PQH can resolve context references
      [user]       — just the raw query
    """
    messages: list[dict[str, str]] = []

    # System: static tool-decision rules — Groq caches this across requests
    messages.append({
        "role": "system",
        "content": pqh_prompt.build_system_prompt(),
    })

    # Real conversation turns — lets PQH resolve "that one", "the same app", etc.
    for turn in recent_context[-_RECENT_TURNS:]:
        role    = str(turn.get("role", "user"))
        content = str(turn.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})

    # Raw query — nothing else mixed in
    messages.append({"role": "user", "content": query})

    return messages


async def chat(
    query: str,
    user_id: str = "guest",
    wait_for_execution: bool = False,
    execution_timeout: float = 30.0,
) -> PQHResponse:
    """
    PQH entry point.
    Decides if a tool is needed, fires SQH in background if so.
    """
    query = (query or "").strip()
    if not query:
        return _error("Empty query", "neutral")

    try:
        # Meta-query shortcut (status/history/log queries)
        if is_meta_query(query):
            meta = await try_handle_meta_query(query=query, user_id=user_id)
            if meta:
                return meta

        # Load user + recent context in parallel
        user_details, recent_context = await asyncio.gather(
            load_user(user_id),
            get_last_n_messages(user_id, n=_RECENT_TURNS),
        )

        if not user_details:
            logger.error("user not found: %s", user_id)
            return _error("User not found. Please log in again.", "neutral", query)

        # Build proper multi-turn messages
        messages = _build_messages(query=query, recent_context=recent_context)

        raw_response, _ = await routed_chat("streaming", messages=messages)

        if not raw_response:
            return clean_pqh_response._create_error_pqh_response("Empty AI response", "neutral")

        cleaned = clean_pqh_response.clean_pqh_response(raw_response, "neutral")

        # Fire SQH if a category was picked (tool action needed)
        if cleaned.category:
            # Multi-turn clarification: PQH flagged the request as ambiguous.
            # Pause here, ask the user one question, then continue with the enriched
            # query so SQH can plan with full context.
            if cleaned.needs_clarification:
                cleaned = await _resolve_clarification(
                    query=query,
                    pqh_response=cleaned,
                    user_id=user_id,
                    user_details=user_details,
                )
                if cleaned is None or not cleaned.category:
                    # Clarification timed out or user gave nothing usable —
                    # return the graceful fallback PQH built and skip SQH.
                    return cleaned or _error(
                        "I didn't catch the details — could you try again?",
                        "neutral",
                        query,
                    )

            if wait_for_execution:
                await _execute_and_wait(cleaned, user_details, user_id, execution_timeout)
            else:
                asyncio.create_task(_run_sqh_background(cleaned, user_details, user_id))

        return cleaned

    except Exception as exc:
        logger.error("chat service error: %s", exc, exc_info=True)
        return _error(str(exc) or "Sorry, I'm having trouble processing your request.", "neutral", query)


async def _execute_and_wait(
    cleaned_response: PQHResponse,
    user_details: dict,
    user_id: str,
    timeout: float = 30.0,
) -> None:
    """Wait for tool execution to complete — used in test/CLI mode only."""
    from app.agent.execution_gateway import get_execution_engine
    try:
        await process_sqh(cleaned_response, user_details)
        engine = get_execution_engine()
        await engine.wait_for_completion(user_id, timeout=timeout)
    except asyncio.TimeoutError:
        logger.error("execution timeout after %.0fs user=%s", timeout, user_id)
    except Exception as exc:
        logger.error("execution error user=%s: %s", user_id, exc, exc_info=True)


def _error(message: str, emotion: str, query: str = "") -> PQHResponse:
    return PQHResponse(
        request_id="error_response",
        cognitive_state=CognitiveState(
            user_query=query,
            emotion=emotion,
            thought_process="Error occurred while processing the request.",
            answer=message,
            answer_english=message,
        ),
        requested_tool=[],
    )