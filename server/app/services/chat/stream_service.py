"""
Streaming Chat Service.

Design goals:
- Fast pre-execution acknowledgement for live/tool-intent queries.
- Stream-first conversational path (LLM token streaming + chunked TTS emit).
- Parallel context loading with strict latency budget.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from app.ai.providers import llm_chat, llm_stream
from app.cache import load_user, get_last_n_messages, process_query_and_get_context
from app.config import settings
from app.prompts import stream_prompt

logger = logging.getLogger(__name__)
_USER_LANG_CACHE: Dict[str, str] = {}
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")


_LIVE_DATA_TOKENS = {
    "today",
    "current",
    "latest",
    "now",
    "live",
    "price",
    "weather",
    "stock",
    "gold",
    "crypto",
    "news",
    "rate",
    "status",
}

_ACTION_TOKENS = {
    "search",
    "open",
    "play",
    "call",
    "send",
    "message",
    "turn",
    "set",
    "check",
    "find",
    "launch",
}

_LIVE_OR_ACTION_RE = re.compile(
    r"\b(search|open|play|call|send|check|find|latest|current|today|price|weather|news|status)\b",
    flags=re.IGNORECASE,
)
_SENTENCE_BREAK_RE = re.compile(r'(?<!\.)(?<!…)[.!?]["\')\]]?\s+')
_CLAUSE_BREAK_RE = re.compile(r'[,;:\u2014]\s+')


def _on_background_done(task: asyncio.Task[Any], label: str) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        return
    except Exception as exc:
        logger.debug("Background task '%s' failed: %s", label, exc)


def _is_live_or_tool_intent(query: str) -> bool:
    normalized = " ".join(query.lower().split())
    if not normalized:
        return False

    if _LIVE_OR_ACTION_RE.search(normalized):
        return True

    tokens = set(re.findall(r"[a-zA-Z_]{2,}", normalized))
    has_live = bool(tokens & _LIVE_DATA_TOKENS)
    has_action = bool(tokens & _ACTION_TOKENS)
    return has_live and has_action


def _resolve_language(user_details: Dict[str, Any] | None) -> str:
    if not user_details:
        return "en"
    lang = str(user_details.get("language", "en")).strip().lower()
    return lang if lang in {"en", "hi", "ne"} else "en"


def _fallback_ack_text(lang: str) -> str:
    if lang == "hi":
        return "ठीक है, अभी करता हूँ।"
    if lang == "ne":
        return "हुन्छ, अहिले गर्छु।"
    return "Got it, working on that now."


def _guess_language_from_query(query: str) -> str:
    # Devanagari implies Hindi/Nepali; prefer Hindi fallback for ack text.
    if _DEVANAGARI_RE.search(query or ""):
        return "hi"
    return "en"


def _remember_user_language(user_id: str, user_details: Dict[str, Any] | None) -> str:
    lang = _resolve_language(user_details)
    _USER_LANG_CACHE[user_id] = lang
    return lang


def _cache_language_from_user_task(task: asyncio.Task[Any], user_id: str) -> None:
    try:
        details = task.result()
    except Exception:
        return

    if isinstance(details, dict):
        _remember_user_language(user_id, details)


def _build_stream_prompt(
    lang: str,
    query: str,
    recent_context: List[Dict[str, Any]],
    query_context: List[Dict[str, Any]],
    user_details: Dict[str, Any],
) -> str:
    emotion = "neutral"
    compact = bool(getattr(settings, "STREAM_USE_COMPACT_PROMPT", False))
    if lang == "hi":
        if compact:
            return stream_prompt.build_compact_prompt_hi(
                emotion, query, recent_context, query_context, user_details
            )
        return stream_prompt.build_prompt_hi(
            emotion, query, recent_context, query_context, user_details
        )
    if lang == "ne":
        if compact:
            return stream_prompt.build_compact_prompt_ne(
                emotion, query, recent_context, query_context, user_details
            )
        return stream_prompt.build_prompt_ne(
            emotion, query, recent_context, query_context, user_details
        )
    if compact:
        return stream_prompt.build_compact_prompt_en(
            emotion, query, recent_context, query_context, user_details
        )
    return stream_prompt.build_prompt_en(
        emotion, query, recent_context, query_context, user_details
    )


def _word_count(text: str) -> int:
    return len(text.split())


def _last_boundary_split(
    pattern: re.Pattern[str],
    buffer: str,
    min_words: int,
) -> int:
    split_index = -1
    for match in pattern.finditer(buffer):
        candidate = buffer[: match.end()]
        if _word_count(candidate) >= min_words:
            split_index = match.end()
    return split_index


def _find_split_point(
    buffer: str,
    min_words: int,
    soft_words: int,
    max_words: int,
) -> int:
    """
    Find the best split point for chunked TTS.

    Priority:
    1) sentence boundary after min_words
    2) clause boundary after soft_words
    3) force split on max_words
    """
    words = buffer.split()
    word_count = len(words)
    if word_count < min_words:
        return -1

    sentence_split = _last_boundary_split(_SENTENCE_BREAK_RE, buffer, min_words)
    if sentence_split > 0:
        return sentence_split

    if word_count >= soft_words:
        clause_split = _last_boundary_split(_CLAUSE_BREAK_RE, buffer, min_words)
        if clause_split > 0:
            return clause_split

    if word_count >= max_words:
        forced = " ".join(words[:max_words])
        return len(forced)

    return -1


def _stream_chunk_thresholds(first_chunk: bool) -> Tuple[int, int, int]:
    base_min = max(2, int(getattr(settings, "STREAM_CHUNK_MIN_WORDS", 5)))
    base_soft = max(base_min + 1, int(getattr(settings, "STREAM_CHUNK_SOFT_WORDS", 12)))
    base_max = max(base_soft + 1, int(getattr(settings, "STREAM_CHUNK_MAX_WORDS", 30)))

    if not first_chunk:
        return base_min, base_soft, base_max

    first_min = max(2, base_min - 2)
    first_soft = max(first_min + 1, base_soft - 2)
    return first_min, first_soft, base_max


async def _iter_stream_with_fast_model(
    messages: List[Dict[str, str]],
    temperature: float,
    max_tokens: int,
) -> AsyncIterator[str]:
    preferred_model = None
    if settings.groq_mode:
        preferred_model = str(getattr(settings, "STREAM_GROQ_FAST_MODEL", "")).strip() or None

    if preferred_model:
        emitted_any = False
        try:
            async for token in llm_stream(
                messages=messages,
                model=preferred_model,
                temperature=temperature,
                max_tokens=max_tokens,
            ):
                emitted_any = True
                yield token
            return
        except Exception as exc:
            if emitted_any:
                raise
            logger.warning(
                "⚠️ [Stream] Preferred fast stream model failed (%s), retrying default model",
                exc,
            )

    async for token in llm_stream(
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    ):
        yield token


async def _chat_with_fast_model(
    messages: List[Dict[str, str]],
    temperature: float,
    max_tokens: int,
) -> tuple[str, str]:
    preferred_model = None
    if settings.groq_mode:
        preferred_model = str(getattr(settings, "STREAM_GROQ_FAST_MODEL", "")).strip() or None

    if preferred_model:
        try:
            return await llm_chat(
                messages=messages,
                model=preferred_model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            logger.warning(
                "⚠️ [Stream] Preferred fast chat model failed (%s), retrying default model",
                exc,
            )

    return await llm_chat(
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )


class StreamService:
    """
    Stream path for user-perceived responsiveness.

    - Live/tool intent: fixed short ack, fast dispatch.
    - Conversational intent: stream LLM response + chunked TTS.
    """

    async def stream_chat_with_tts(
        self,
        query: str,
        user_id: str,
        sio: Any,
        sid: str,
        tts_service: Any,
        gender: str = "female",
    ) -> bool:
        request_id = uuid.uuid4().hex[:8]
        request_started = time.perf_counter()
        query = (query or "").strip()
        if not query:
            logger.warning("⚠️ Empty query received in stream_chat_with_tts")
            return False

        gate_started = time.perf_counter()
        live_or_tool = _is_live_or_tool_intent(query)
        if not settings.STREAM_ONE_SHOT_TTS_ENABLED:
            # Compatibility toggle: disable fast one-shot ack gate when rollout is off.
            live_or_tool = False
        logger.info(
            "⚡ [Stream] request_id=%s intent_gate=%s duration_ms=%.0f",
            request_id,
            "live/tool" if live_or_tool else "conversation",
            (time.perf_counter() - gate_started) * 1000,
        )

        if settings.STREAM_FAST_ACK_ENABLED and live_or_tool:
            # Ultra-fast path: avoid upstream LLM/context waits before first audio.
            user_task = asyncio.create_task(load_user(user_id))
            user_task.add_done_callback(lambda t, uid=user_id: _cache_language_from_user_task(t, uid))
            user_task.add_done_callback(lambda t: _on_background_done(t, "user_details"))

            lang = _USER_LANG_CACHE.get(user_id) or _guess_language_from_query(query)
            ack_text = _fallback_ack_text(lang)

            tts_dispatch_started = time.perf_counter()
            success = await tts_service.stream_to_socket(
                sio=sio,
                sid=sid,
                text=ack_text,
                gender=gender,
            )
            tts_dispatch_ms = (time.perf_counter() - tts_dispatch_started) * 1000
            total_ms = (time.perf_counter() - request_started) * 1000
            logger.info(
                "📡 [Stream] request_id=%s fast_ack_tts_dispatch_ms=%.0f total_ms=%.0f text=%s",
                request_id,
                tts_dispatch_ms,
                total_ms,
                ack_text,
            )
            return success

        # Conversational path: await user/recent and bounded query-context.
        # Kick off context work in parallel only when we actually need it.
        user_task = asyncio.create_task(load_user(user_id))
        recent_task = asyncio.create_task(get_last_n_messages(user_id, n=10))
        context_task = asyncio.create_task(
            process_query_and_get_context(
                user_id=user_id,
                query=query,
                budget_ms=settings.STREAM_CONTEXT_BUDGET_MS,
                top_k=6,
                threshold=0.1,
                fast_lane=True,
            )
        )

        try:
            user_details = await user_task
        except Exception as exc:
            logger.error("❌ [Stream] Failed to load user details: %s", exc, exc_info=True)
            return False

        if not user_details:
            logger.error("❌ [Stream] User %s not found", user_id)
            return False
        _remember_user_language(user_id, user_details)

        try:
            recent_context = await recent_task
        except Exception:
            recent_context = []

        query_context: List[Dict[str, Any]] = []
        context_started = time.perf_counter()
        try:
            result_context, _ = await asyncio.wait_for(
                context_task,
                timeout=max(0.05, settings.STREAM_CONTEXT_BUDGET_MS / 1000.0),
            )
            query_context = result_context or []
        except asyncio.TimeoutError:
            logger.info("⏱️ [Stream] query_context timeout at %sms; using empty context", settings.STREAM_CONTEXT_BUDGET_MS)
            context_task.cancel()
        except Exception as exc:
            logger.warning("⚠️ [Stream] query_context failed, using empty context: %s", exc)
        context_ms = (time.perf_counter() - context_started) * 1000
        logger.info(
            "🧠 [Stream] request_id=%s context_ms=%.0f context_results=%d",
            request_id,
            context_ms,
            len(query_context),
        )

        lang = _resolve_language(user_details)
        prompt = _build_stream_prompt(
            lang=lang,
            query=query,
            recent_context=recent_context,
            query_context=query_context,
            user_details=user_details,
        )

        messages = [{"role": "user", "content": prompt}]
        first_llm_token_ms: Optional[float] = None
        first_tts_dispatch_ms: Optional[float] = None
        emitted_chunks = 0
        full_response = ""
        llm_started = time.perf_counter()

        queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

        async def _tts_consumer() -> bool:
            nonlocal first_tts_dispatch_ms, emitted_chunks
            while True:
                chunk_text = await queue.get()
                try:
                    if chunk_text is None:
                        return True

                    tts_dispatch_started = time.perf_counter()
                    if first_tts_dispatch_ms is None:
                        first_tts_dispatch_ms = (tts_dispatch_started - request_started) * 1000

                    ok = await tts_service.stream_to_socket(
                        sio=sio,
                        sid=sid,
                        text=chunk_text,
                        gender=gender,
                    )
                    emitted_chunks += 1
                    if not ok:
                        logger.warning("⚠️ [Stream] request_id=%s tts chunk emit failed", request_id)
                        return False
                finally:
                    queue.task_done()

        consumer_task = asyncio.create_task(_tts_consumer())
        produced_chunks = 0
        buffer = ""
        stream_error: Optional[Exception] = None

        async def _enqueue_chunk(chunk_text: str) -> None:
            nonlocal produced_chunks
            normalized = " ".join((chunk_text or "").split())
            if not normalized:
                return
            produced_chunks += 1
            await queue.put(normalized)

        try:
            if bool(getattr(settings, "STREAM_USE_LLM_STREAM", True)):
                async for token in _iter_stream_with_fast_model(
                    messages=messages,
                    temperature=0.3,
                    max_tokens=220,
                ):
                    if not token:
                        continue

                    if first_llm_token_ms is None:
                        first_llm_token_ms = (time.perf_counter() - request_started) * 1000

                    buffer += token
                    full_response += token

                    while True:
                        min_words, soft_words, max_words = _stream_chunk_thresholds(
                            first_chunk=(produced_chunks == 0)
                        )
                        split_at = _find_split_point(
                            buffer=buffer,
                            min_words=min_words,
                            soft_words=soft_words,
                            max_words=max_words,
                        )
                        if split_at <= 0:
                            break
                        chunk = buffer[:split_at].strip()
                        buffer = buffer[split_at:].lstrip()
                        await _enqueue_chunk(chunk)
            else:
                llm_result, _ = await _chat_with_fast_model(
                    messages=messages,
                    temperature=0.3,
                    max_tokens=220,
                )
                full_response = (llm_result or "").strip()
                if full_response:
                    await _enqueue_chunk(full_response)
        except Exception as exc:
            stream_error = exc

        if buffer.strip():
            await _enqueue_chunk(buffer.strip())

        if stream_error and produced_chunks == 0:
            logger.warning(
                "⚠️ [Stream] request_id=%s llm stream failed before first chunk; falling back to llm_chat: %s",
                request_id,
                stream_error,
            )
            try:
                fallback_result, _ = await _chat_with_fast_model(
                    messages=messages,
                    temperature=0.3,
                    max_tokens=220,
                )
                full_response = (fallback_result or "").strip()
                if full_response:
                    await _enqueue_chunk(full_response)
            except Exception as exc:
                logger.error("❌ [Stream] request_id=%s LLM fallback failed: %s", request_id, exc, exc_info=True)
                consumer_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await consumer_task
                return False

        if not full_response.strip() and produced_chunks == 0:
            await _enqueue_chunk(_fallback_ack_text(lang))

        await queue.put(None)
        tts_success = await consumer_task

        llm_ms = (time.perf_counter() - llm_started) * 1000
        total_ms = (time.perf_counter() - request_started) * 1000
        logger.info(
            "✅ [Stream] request_id=%s first_llm_token_ms=%s first_tts_dispatch_ms=%s context_ms=%.0f llm_window_ms=%.0f total_ms=%.0f produced_chunks=%d emitted_chunks=%d chars=%d slo_ms=%d",
            request_id,
            f"{first_llm_token_ms:.0f}" if first_llm_token_ms is not None else "na",
            f"{first_tts_dispatch_ms:.0f}" if first_tts_dispatch_ms is not None else "na",
            context_ms,
            llm_ms,
            total_ms,
            produced_chunks,
            emitted_chunks,
            len(full_response),
            int(getattr(settings, "STREAM_FIRST_AUDIO_SLO_MS", 1000)),
        )
        return tts_success


# ==================== CONVENIENCE FUNCTIONS ====================

async def stream_chat_response(
    query: str,
    user_id: str,
    sio: Any,
    sid: str,
    tts_service: Any,
    gender: str = "female",
) -> bool:
    """Quick helper for stream path with TTS."""
    service = StreamService()
    return await service.stream_chat_with_tts(
        query=query,
        user_id=user_id,
        sio=sio,
        sid=sid,
        tts_service=tts_service,
        gender=gender,
    )


async def parallel_chat_execution(
    query: str,
    user_id: str,
    sio: Any,
    sid: str,
    tts_service: Any,
    gender: str = "female",
) -> Dict[str, Any]:
    """
    Run stream (voice path) and chat (PQH→SQH) in parallel.

    Stream stays independent so user gets immediate audio feedback while
    tool orchestration proceeds.
    """
    from .chat_service import chat

    async def _independent_stream() -> None:
        try:
            await stream_chat_response(
                query=query,
                user_id=user_id,
                sio=sio,
                sid=sid,
                tts_service=tts_service,
                gender=gender,
            )
        except Exception as exc:
            logger.error("❌ Independent stream failed: %s", exc, exc_info=True)

    stream_bg_task = asyncio.create_task(_independent_stream())
    logger.info("🎤 Stream launched as independent background task for %s", user_id)

    chat_result = None
    try:
        chat_result = await chat(
            query=query,
            user_id=user_id,
            wait_for_execution=False,
        )
    except Exception as exc:
        logger.error("❌ Chat failed: %s", exc, exc_info=True)

    return {
        "stream_success": not stream_bg_task.done() or not stream_bg_task.cancelled(),
        "chat_result": chat_result,
    }
