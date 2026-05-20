"""
Clarification Service — multi-turn agent loop.

When PQH detects a tool-requiring query that's too ambiguous to plan,
this service asks the user a clarifying question, waits for the response,
then re-invokes SQH with the enriched context.

Flow:
  1. PQH returns requested_tool + needs_clarification signal
  2. ClarificationService generates a short question via LLM
  3. Question is sent to client via socket (text + TTS)
  4. User responds (voice or text)
  5. Original query + clarification answer → SQH builds the plan
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Dict, Optional

from app.ai.providers import llm_chat, routed_chat
from app.models.pqh_response_model import PQHResponse

logger = logging.getLogger(__name__)

# In-flight clarification requests: request_id → asyncio.Future[str]
_pending: Dict[str, asyncio.Future[str]] = {}
# Reverse index so we can resolve / cancel by user_id without scanning everything
_owner: Dict[str, str] = {}  # request_id → user_id


CLARIFICATION_SYSTEM_PROMPT = """You are SPARK's clarification module.
The user asked something that requires a tool action, but key details are missing.
Your ONLY job: ask ONE short, natural clarifying question (under 20 words).

Rules:
- Ask the MINIMUM needed to proceed. Don't ask for things you can assume.
- Be conversational, not robotic.
- Never list options unless there are exactly 2-3 obvious choices.
- Ask in {lang}.
- Output ONLY the question text. No JSON, no explanation."""


async def generate_clarification_question(
    query: str,
    thought_process: str,
    tools: list[str],
    lang: str = "English",
) -> str:
    """Ask the LLM to produce a short clarifying question."""
    messages = [
        {"role": "system", "content": CLARIFICATION_SYSTEM_PROMPT.format(lang=lang)},
        {"role": "user", "content": (
            f"User query: \"{query}\"\n"
            f"Intent analysis: {thought_process}\n"
            f"Tools that would be needed: {tools}\n"
            f"What single question should I ask to fill in the missing detail?"
        )},
    ]
    try:
        response, _ = await routed_chat("lightweight", messages=messages, max_tokens=60, temperature=0.4)
        return (response or "").strip().strip('"')
    except Exception as exc:
        logger.error("Failed to generate clarification question: %s", exc)
        return "Could you give me more details on what exactly you'd like me to do?"


async def request_clarification(
    user_id: str,
    original_query: str,
    pqh_response: PQHResponse,
    user_details: Dict[str, Any],
    timeout: float = 60.0,
) -> Optional[str]:
    """
    Send a clarification question to the user and wait for the response.

    Returns the user's answer string, or None on timeout/error.
    """
    request_id = f"clarify_{uuid.uuid4().hex[:8]}"
    lang_map = {"hi": "Hindi", "ne": "Nepali", "en": "English"}
    lang = lang_map.get(user_details.get("lang", "en"), "English")

    tools = [pqh_response.category] if pqh_response.category else []
    thought = pqh_response.cognitive_state.thought_process

    question = await generate_clarification_question(
        query=original_query,
        thought_process=thought,
        tools=tools,
        lang=lang,
    )

    if not question:
        return None

    loop = asyncio.get_running_loop()
    future: asyncio.Future[str] = loop.create_future()
    _pending[request_id] = future
    _owner[request_id] = user_id

    try:
        # Emit to client via socket
        from app.socket.utils import socket_emit_to_users, stream_tts_to_client
        await socket_emit_to_users("agent:clarify", {
            "request_id": request_id,
            "question": question,
            "original_query": original_query,
        }, [user_id])

        # Also speak the question via TTS
        asyncio.create_task(stream_tts_to_client(question, user_id=user_id))

        # Wait for user response
        answer = await asyncio.wait_for(future, timeout=timeout)
        return answer

    except asyncio.TimeoutError:
        logger.warning("Clarification timeout for user=%s request=%s", user_id, request_id)
        return None
    except asyncio.CancelledError:
        logger.info("Clarification cancelled user=%s request=%s", user_id, request_id)
        return None
    except Exception as exc:
        logger.error("Clarification failed for user=%s: %s", user_id, exc)
        return None
    finally:
        _pending.pop(request_id, None)
        _owner.pop(request_id, None)


def resolve_clarification(request_id: str, answer: str) -> bool:
    """Called when the client sends back a clarification response by request_id."""
    future = _pending.get(request_id)
    if future and not future.done():
        future.set_result(answer)
        return True
    return False


def has_pending_clarification(user_id: str) -> bool:
    """True if there is at least one in-flight clarification for this user."""
    return any(
        owner == user_id and not _pending[rid].done()
        for rid, owner in _owner.items()
        if rid in _pending
    )


def resolve_user_clarification(user_id: str, answer: str) -> bool:
    """
    Resolve the most recent pending clarification for `user_id` with `answer`.

    Used when the user answers via the regular text/voice channel instead of
    the dedicated `agent:clarify:response` event. Returns True if an answer
    was routed, False if no pending clarification existed.
    """
    # Most-recent-first: clarifications are appended in order, so iterate reversed.
    for request_id in reversed(list(_owner.keys())):
        if _owner.get(request_id) != user_id:
            continue
        future = _pending.get(request_id)
        if future and not future.done():
            future.set_result(answer)
            return True
    return False


def cancel_user_clarifications(user_id: str) -> None:
    """Cancel all pending clarifications for a user (e.g. on disconnect)."""
    to_remove = [rid for rid, owner in _owner.items() if owner == user_id]
    for rid in to_remove:
        future = _pending.get(rid)
        if future and not future.done():
            future.cancel()
        _pending.pop(rid, None)
        _owner.pop(rid, None)
