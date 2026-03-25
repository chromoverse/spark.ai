"""
Streaming Chat Service.

Flow:
  1. Parallel: user details + recent messages + RAG context
  2. Build proper multi-turn messages array
  3. Stream LLM tokens → split into TTS chunks via producer/consumer queue
     └─ if stream fails entirely → fallback to llm_chat (non-stream)
     └─ if llm_chat also fails → emit _fallback_text() as last resort

Fixes applied:
  - Model always injected from GROQ_DEFAULT_MODEL (not gated on groq_mode)
  - RAG budget reduced to STREAM_CONTEXT_BUDGET_MS (200 ms default)
  - TTS consumer runs chunks concurrently (bounded semaphore, 2 parallel)
  - _RECENT_TURNS reduced to 5 for faster DB load
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.ai.providers import llm_chat, llm_stream
from app.cache import add_message, load_user, get_last_n_messages, process_query_and_get_context
from app.config import settings
from app.prompts import stream_prompt
from app.services.interrupt_manager import get_interrupt_manager

logger = logging.getLogger(__name__)
_interrupt = get_interrupt_manager()

_SENTENCE_BREAK_RE = re.compile(r'(?<!\.)(?<!…)[.!?]["\'\)\]]?\s+')
_CLAUSE_BREAK_RE   = re.compile(r'[,;:\u2014]\s+')

_RECENT_TURNS      = 5      # reduced from 8 — fewer DB rows, same quality
_LLM_TEMPERATURE   = 0.3
_LLM_MAX_TOKENS    = 220
_TTS_CONCURRENCY   = 2      # concurrent TTS requests (tune to your TTS service)


def _context_budget_ms() -> int:
    return int(getattr(settings, "STREAM_CONTEXT_BUDGET_MS", 200))


def _context_top_k() -> int:
    return int(getattr(settings, "STREAM_CONTEXT_TOP_K", 8))


def _resolve_language(user_details: Dict[str, Any] | None) -> str:
    if not user_details:
        return "en"
    lang = str(user_details.get("language", "en")).strip().lower()
    return lang if lang in {"en", "hi", "ne"} else "en"


def _fallback_text(lang: str) -> str:
    if lang == "hi": return "ठीक है, अभी करता हूँ।"
    if lang == "ne": return "हुन्छ, अहिले गर्छु।"
    return "Got it, sir!"


def _format_rag_chunks(query_context: List[Dict[str, Any]]) -> str:
    lines = []
    for i, chunk in enumerate(query_context, 1):
        content = str(chunk.get("content") or "").strip()
        if content:
            lines.append(f"[{i}] {content}")
    return "\n".join(lines)


def _build_messages(
    lang: str,
    query: str,
    recent_context: List[Dict[str, Any]],
    query_context: List[Dict[str, Any]],
    user_details: Dict[str, Any],
) -> List[Dict[str, str]]:
    messages: List[Dict[str, str]] = []

    messages.append({
        "role": "system",
        "content": stream_prompt.build_system_prompt(lang=lang, user_details=user_details),
    })
    for turn in recent_context[-_RECENT_TURNS:]:
        role    = str(turn.get("role", "user"))
        content = str(turn.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})

    rag_text = _format_rag_chunks(query_context)
    if rag_text:
        messages.append({"role": "system", "content": f"Relevant context:\n{rag_text}"})

    messages.append({"role": "user", "content": query})
    return messages


def _word_count(text: str) -> int:
    return len(text.split())


def _last_boundary_split(pattern: re.Pattern[str], buffer: str, min_words: int) -> int:
    split_index = -1
    for match in pattern.finditer(buffer):
        if _word_count(buffer[: match.end()]) >= min_words:
            split_index = match.end()
    return split_index


def _find_split_point(buffer: str, min_words: int, soft_words: int, max_words: int) -> int:
    if _word_count(buffer) < min_words:
        return -1
    s = _last_boundary_split(_SENTENCE_BREAK_RE, buffer, min_words)
    if s > 0:
        return s
    if _word_count(buffer) >= soft_words:
        c = _last_boundary_split(_CLAUSE_BREAK_RE, buffer, min_words)
        if c > 0:
            return c
    if _word_count(buffer) >= max_words:
        return len(" ".join(buffer.split()[:max_words]))
    return -1


def _chunk_thresholds(first_chunk: bool) -> Tuple[int, int, int]:
    base_min  = max(2,            int(getattr(settings, "STREAM_CHUNK_MIN_WORDS",  5)))
    base_soft = max(base_min + 1, int(getattr(settings, "STREAM_CHUNK_SOFT_WORDS", 12)))
    base_max  = max(base_soft + 1,int(getattr(settings, "STREAM_CHUNK_MAX_WORDS",  30)))
    if not first_chunk:
        return base_min, base_soft, base_max
    return max(2, base_min - 2), max(3, base_soft - 2), base_max


def _model_kwargs(messages: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Build LLM call kwargs.

    FIX: Always inject GROQ_DEFAULT_MODEL when it is configured — previously
    this was gated on `settings.groq_mode`, so stream_service would omit the
    model while the mini-test always passed it explicitly, causing different
    behaviour between the two call sites.
    """
    kwargs: Dict[str, Any] = dict(
        messages=messages,
        temperature=_LLM_TEMPERATURE,
        max_tokens=_LLM_MAX_TOKENS,
    )
    model = str(getattr(settings, "GROQ_DEFAULT_MODEL", "")).strip()
    if model:
        kwargs["model"] = model
    return kwargs


class StreamService:

    async def stream_chat_with_tts(
        self,
        query: str,
        user_id: str,
        sio: Any,
        sid: str,
        tts_service: Any,
        gender: str = "female",
        voice_name: Optional[str] = None,
    ) -> bool:
        query = (query or "").strip()
        if not query:
            return False

        request_id = uuid.uuid4().hex[:8]

        # ── 1. Parallel context load ──────────────────────────────────────────
        budget_ms = _context_budget_ms()   # 200 ms default (was hardcoded 800 ms)

        user_task    = asyncio.create_task(load_user(user_id))
        recent_task  = asyncio.create_task(get_last_n_messages(user_id, n=_RECENT_TURNS))
        context_task = asyncio.create_task(
            process_query_and_get_context(
                user_id=user_id,
                query=query,
                budget_ms=budget_ms,
                top_k=_context_top_k(),
                threshold=0.08,
                fast_lane=True,
            )
        )
        persist_task = asyncio.create_task(
            add_message(user_id=user_id, role="user", content=query)
        )
        persist_task.add_done_callback(
            lambda t: t.exception() and logger.debug("[%s] persist user msg failed", request_id)
        )

        try:
            user_details = await user_task
        except Exception:
            logger.error("[%s] failed to load user", request_id)
            return False
        if not user_details:
            return False

        try:
            recent_context = await recent_task
        except Exception:
            recent_context = []

        query_context: List[Dict[str, Any]] = []
        try:
            result, _ = await asyncio.wait_for(
                context_task, timeout=budget_ms / 1000.0
            )
            query_context = result or []
        except (asyncio.TimeoutError, Exception):
            context_task.cancel()

        # ── 2. Build messages ─────────────────────────────────────────────────
        lang     = _resolve_language(user_details)
        messages = _build_messages(
            lang=lang, query=query,
            recent_context=recent_context,
            query_context=query_context,
            user_details=user_details,
        )
        kwargs = _model_kwargs(messages)

        # ── 3. LLM stream → TTS queue ─────────────────────────────────────────
        queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
        produced      = 0
        full_response = ""
        buffer        = ""

        # ── TTS consumer — concurrent with bounded semaphore ─────────────────
        # FIX: previously each chunk was sent serially; if TTS takes ~300 ms
        # per chunk and you have 4 chunks, that's 1.2 s of pure wait.
        # With a semaphore of 2 we overlap TTS calls while keeping order
        # guarantees relaxed (audio chunks may arrive slightly out of order
        # if your TTS/socket layer requires strict order, drop to sem=1).
        async def _tts_consumer() -> bool:
            sem   = asyncio.Semaphore(_TTS_CONCURRENCY)
            tasks: List[asyncio.Task] = []

            async def _handle(chunk: str) -> bool:
                async with sem:
                    return await tts_service.stream_to_socket(
                        sio=sio, sid=sid, text=chunk,
                        voice=voice_name, gender=gender,
                        interrupt_check=lambda: _interrupt.is_set(user_id),
                    )

            while True:
                chunk = await queue.get()
                try:
                    if chunk is None:
                        break
                    if _interrupt.is_set(user_id):
                        logger.info("[%s] TTS consumer interrupted — draining queue", request_id)
                        queue.task_done()
                        # Drain remaining items
                        while not queue.empty():
                            try:
                                queue.get_nowait()
                                queue.task_done()
                            except asyncio.QueueEmpty:
                                break
                        return True
                    tasks.append(asyncio.create_task(_handle(chunk)))
                finally:
                    queue.task_done()

            if not tasks:
                return True
            results = await asyncio.gather(*tasks, return_exceptions=True)
            return all(r is True for r in results)

        async def _enqueue(text: str) -> None:
            nonlocal produced
            normalized = " ".join((text or "").split())
            if normalized:
                produced += 1
                await queue.put(normalized)

        consumer_task = asyncio.create_task(_tts_consumer())

        # ── Try streaming first ───────────────────────────────────────────────
        stream_exc: Optional[Exception] = None
        try:
            async for token in llm_stream(**kwargs):
                if not token:
                    continue
                # Fast interrupt check — dict lookup + bool, zero-cost when not set
                if _interrupt.is_set(user_id):
                    logger.info("[%s] LLM stream interrupted by user", request_id)
                    break
                buffer        += token
                full_response += token
                while True:
                    min_w, soft_w, max_w = _chunk_thresholds(produced == 0)
                    split_at = _find_split_point(buffer, min_w, soft_w, max_w)
                    if split_at <= 0:
                        break
                    await _enqueue(buffer[:split_at].strip())
                    buffer = buffer[split_at:].lstrip()

        except Exception as exc:
            stream_exc = exc
            logger.error("[%s] LLM stream failed: %s", request_id, exc)

        # Flush remaining buffer from stream
        if buffer.strip():
            await _enqueue(buffer.strip())

        # ── Stream produced nothing → try llm_chat as fallback ───────────────
        if produced == 0:
            if stream_exc:
                logger.warning("[%s] stream produced nothing — falling back to llm_chat", request_id)
            else:
                logger.warning("[%s] stream completed but yielded 0 tokens — falling back to llm_chat", request_id)
            try:
                # Drop provider-specific model so each provider uses its own default
                fallback_kwargs = {k: v for k, v in kwargs.items() if k != "model"}
                chat_response, _ = await llm_chat(**fallback_kwargs)
                full_response = (chat_response or "").strip()
                if full_response:
                    await _enqueue(full_response)
                else:
                    logger.warning("[%s] llm_chat also returned empty — using hardcoded fallback", request_id)
                    await _enqueue(_fallback_text(lang))
            except Exception as exc:
                logger.error("[%s] llm_chat fallback also failed: %s — using hardcoded fallback", request_id, exc)
                await _enqueue(_fallback_text(lang))

        await queue.put(None)
        success = await consumer_task

        # ── 4. Persist assistant response ─────────────────────────────────────
        msg = " ".join(full_response.split()).strip()
        if msg:
            bg = asyncio.create_task(
                add_message(user_id=user_id, role="assistant", content=msg)
            )
            bg.add_done_callback(
                lambda t: t.exception() and logger.debug("[%s] persist assistant msg failed", request_id)
            )

        return success


async def stream_chat_response(
    query: str,
    user_id: str,
    sio: Any,
    sid: str,
    tts_service: Any,
    gender: str = "female",
    voice_name: Optional[str] = None,
) -> bool:
    return await StreamService().stream_chat_with_tts(
        query=query, user_id=user_id, sio=sio, sid=sid,
        tts_service=tts_service, gender=gender, voice_name=voice_name,
    )