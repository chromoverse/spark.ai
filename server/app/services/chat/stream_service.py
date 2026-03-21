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

logger = logging.getLogger(__name__)

_SENTENCE_BREAK_RE = re.compile(r'(?<!\.)(?<!…)[.!?]["\'\)\]]?\s+')
_CLAUSE_BREAK_RE   = re.compile(r'[,;:\u2014]\s+')

_RECENT_TURNS      = 5      # reduced from 8 — fewer DB rows, same quality
_LLM_TEMPERATURE   = 0.3
_LLM_MAX_TOKENS    = 220
_TTS_CONCURRENCY   = 2      # concurrent TTS requests (tune to your TTS service)


<<<<<<< HEAD
def _context_budget_ms() -> int:
    return int(getattr(settings, "STREAM_CONTEXT_BUDGET_MS", 200))


def _context_top_k() -> int:
    return int(getattr(settings, "STREAM_CONTEXT_TOP_K", 8))
=======
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
    r"\b(search|open|play|call|send|check|find|latest|current|today|price|weather|news)\b",
    flags=re.IGNORECASE,
)
_INTERNAL_CONTEXT_TOKENS = {
    "server",
    "tool",
    "tools",
    "task",
    "tasks",
    "history",
    "memory",
    "workflow",
    "execution",
}
# Hard cap only for non-fast-lane desktop requests.
DESKTOP_CONTEXT_WAIT_TIMEOUT_MS = 300
_SENTENCE_BREAK_RE = re.compile(r'(?<!\.)(?<!…)[.!?]["\')\]]?\s+')
_CLAUSE_BREAK_RE = re.compile(r'[,;:\u2014]\s+')
_STREAM_CONTEXT_TOKEN_RE = re.compile(r"\w+", flags=re.UNICODE)
_STREAM_RECENT_CONTEXT_FALLBACK_LIMIT = 3


def _on_background_done(task: asyncio.Task[Any], label: str) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        return
    except Exception as exc:
        logger.debug("Background task '%s' failed: %s", label, exc)


async def _emit_stream_event(sio: Any, sid: str, event: str, payload: Dict[str, Any]) -> None:
    """Best-effort stream lifecycle emit that never interrupts main flow."""
    try:
        await sio.emit(event, payload, to=sid)
    except Exception as exc:
        logger.debug("Stream lifecycle emit failed event=%s sid=%s err=%s", event, sid, exc)


def _is_live_or_tool_intent(query: str) -> bool:
    normalized = " ".join(query.lower().split())
    if not normalized:
        return False

    tokens = set(re.findall(r"[a-zA-Z_]{2,}", normalized))
    has_live = bool(tokens & _LIVE_DATA_TOKENS)
    has_action = bool(tokens & _ACTION_TOKENS)
    has_internal_context = bool(tokens & _INTERNAL_CONTEXT_TOKENS)

    # Internal status/memory questions should go through full conversational path.
    if has_internal_context and not has_action:
        return False

    if has_action:
        return True

    if has_live and _LIVE_OR_ACTION_RE.search(normalized):
        return True

    return False
>>>>>>> 7ff3f566494ef823f1013bcd9bc269d63d0fb839


def _resolve_language(user_details: Dict[str, Any] | None) -> str:
    if not user_details:
        return "en"
    lang = str(user_details.get("language", "en")).strip().lower()
    return lang if lang in {"en", "hi", "ne"} else "en"


<<<<<<< HEAD
def _fallback_text(lang: str) -> str:
    if lang == "hi": return "ठीक है, अभी करता हूँ।"
    if lang == "ne": return "हुन्छ, अहिले गर्छु।"
    return "Got it, sir!"
=======
def _fallback_ack_text(lang: str) -> str:
    if lang == "hi":
        return "ठीक है, अभी करता हूँ।"
    if lang == "ne":
        return "हुन्छ, अहिले गर्छु।"
    return "Got it Sir, working on it."
>>>>>>> 7ff3f566494ef823f1013bcd9bc269d63d0fb839


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
        latency_trace: Optional[Dict[str, Any]] = None,
    ) -> bool:
<<<<<<< HEAD
=======
        request_id = uuid.uuid4().hex[:8]
        request_started = time.perf_counter()
        stream_started_epoch_ms = time.time() * 1000.0
        latency_trace = latency_trace or {}
        speech_end_ts_ms = int(latency_trace.get("speech_end_ts_ms") or 0)
        stt_ready_ms = float(latency_trace.get("stt_ready_ms") or 0.0)

        async def _emit_latency_metrics(
            *,
            first_llm_token_ms: Optional[float],
            first_tts_dispatch_ms: Optional[float],
            context_ms: float,
            total_ms: float,
            emitted_chunks: int,
            chars: int,
            success: bool,
            error: Optional[str] = None,
        ) -> None:
            speech_to_first_tts_ms: Optional[float] = None
            if speech_end_ts_ms > 0 and first_tts_dispatch_ms is not None:
                speech_to_first_tts_ms = max(
                    0.0,
                    (stream_started_epoch_ms + float(first_tts_dispatch_ms))
                    - float(speech_end_ts_ms),
                )

            payload: Dict[str, Any] = {
                "requestId": request_id,
                "success": success,
                "sttReadyMs": round(stt_ready_ms, 1) if stt_ready_ms > 0 else None,
                "speechToFirstTtsMs": round(speech_to_first_tts_ms, 1)
                if speech_to_first_tts_ms is not None
                else None,
                "firstLlmTokenMs": round(first_llm_token_ms, 1)
                if first_llm_token_ms is not None
                else None,
                "firstTtsDispatchMs": round(first_tts_dispatch_ms, 1)
                if first_tts_dispatch_ms is not None
                else None,
                "contextMs": round(context_ms, 1),
                "totalMs": round(total_ms, 1),
                "emittedChunks": emitted_chunks,
                "chars": chars,
            }
            if error:
                payload["error"] = error
            await _emit_stream_event(sio, sid, "latency-metrics", payload)

        async def _emit_ai_end(success: bool, error: Optional[str] = None) -> None:
            payload: Dict[str, Any] = {"requestId": request_id, "success": success}
            if error:
                payload["error"] = error
            await _emit_stream_event(sio, sid, "ai-end", payload)

>>>>>>> 7ff3f566494ef823f1013bcd9bc269d63d0fb839
        query = (query or "").strip()
        if not query:
            return False
        await _emit_stream_event(sio, sid, "ai-start", {"requestId": request_id})

        request_id = uuid.uuid4().hex[:8]

        # ── 1. Parallel context load ──────────────────────────────────────────
        budget_ms = _context_budget_ms()   # 200 ms default (was hardcoded 800 ms)

<<<<<<< HEAD
        user_task    = asyncio.create_task(load_user(user_id))
        recent_task  = asyncio.create_task(get_last_n_messages(user_id, n=_RECENT_TURNS))
=======
            persist_task = asyncio.create_task(add_message(user_id=user_id, role="user", content=query))
            persist_task.add_done_callback(lambda t: _on_background_done(t, "add_message(fast_ack)"))

            lang = _USER_LANG_CACHE.get(user_id) or _guess_language_from_query(query)
            ack_text = _fallback_ack_text(lang)

            tts_dispatch_started = time.perf_counter()
            success = await tts_service.stream_to_socket(
                sio=sio,
                sid=sid,
                text=ack_text,
                voice=voice_name,
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
            assistant_task = asyncio.create_task(
                add_message(user_id=user_id, role="assistant", content=ack_text)
            )
            assistant_task.add_done_callback(
                lambda t: _on_background_done(t, "add_message(fast_ack_assistant)")
            )
            await _emit_ai_end(success=success, error=None if success else "tts_stream_failed")
            await _emit_latency_metrics(
                first_llm_token_ms=None,
                first_tts_dispatch_ms=tts_dispatch_ms,
                context_ms=0.0,
                total_ms=total_ms,
                emitted_chunks=1 if success else 0,
                chars=len(ack_text),
                success=success,
                error=None if success else "tts_stream_failed",
            )
            return success

        # Conversational path: await user/recent and bounded query-context.
        # Kick off context work in parallel only when we actually need it.
        context_budget_ms = max(
            50,
            int(getattr(settings, "STREAM_CONTEXT_BUDGET_MS", settings.STREAM_CONTEXT_TARGET_MS)),
        )
        fast_lane = True
        user_task = asyncio.create_task(load_user(user_id))
        recent_task = asyncio.create_task(get_last_n_messages(user_id, n=10))
>>>>>>> 7ff3f566494ef823f1013bcd9bc269d63d0fb839
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
<<<<<<< HEAD
        except Exception:
            logger.error("[%s] failed to load user", request_id)
=======
        except Exception as exc:
            logger.error("❌ [Stream] Failed to load user details: %s", exc, exc_info=True)
            await _emit_ai_end(success=False, error="user_load_failed")
>>>>>>> 7ff3f566494ef823f1013bcd9bc269d63d0fb839
            return False
        if not user_details:
<<<<<<< HEAD
=======
            logger.error("❌ [Stream] User %s not found", user_id)
            await _emit_ai_end(success=False, error="user_not_found")
>>>>>>> 7ff3f566494ef823f1013bcd9bc269d63d0fb839
            return False

        try:
            recent_context = await recent_task
        except Exception:
            recent_context = []

        query_context: List[Dict[str, Any]] = []
<<<<<<< HEAD
=======
        context_started = time.perf_counter()
        context_timeout_ms = context_budget_ms
        context_top_k = max(1, int(getattr(settings, "STREAM_CONTEXT_TOP_K", 8)))
        if settings.environment == "DESKTOP" and not fast_lane:
            context_timeout_ms = max(context_timeout_ms, DESKTOP_CONTEXT_WAIT_TIMEOUT_MS)
>>>>>>> 7ff3f566494ef823f1013bcd9bc269d63d0fb839
        try:
            result, _ = await asyncio.wait_for(
                context_task, timeout=budget_ms / 1000.0
            )
            query_context = result or []
        except (asyncio.TimeoutError, Exception):
            context_task.cancel()

<<<<<<< HEAD
        # ── 2. Build messages ─────────────────────────────────────────────────
        lang     = _resolve_language(user_details)
        messages = _build_messages(
            lang=lang, query=query,
=======
        if settings.environment == "PRODUCTION" and (not query_context) and recent_context:
            query_context = _build_query_context_from_recent(
                query=query,
                recent_context=recent_context,
                limit=context_top_k,
            )
            if query_context:
                logger.info(
                    "🧩 [Stream] request_id=%s recovered query_context from recent messages count=%d",
                    request_id,
                    len(query_context),
                )

        context_ms = (time.perf_counter() - context_started) * 1000
        top_context_score = 0.0
        if query_context:
            def _safe_score(item: Dict[str, Any]) -> float:
                try:
                    return float(item.get("score", item.get("_similarity_score", 0)) or 0)
                except (TypeError, ValueError):
                    return 0.0
            top_context_score = max(
                _safe_score(item)
                for item in query_context
            )
        logger.info(
            "🧠 [Stream] request_id=%s context_ms=%.0f context_results=%d top_context_score=%.4f budget_ms=%s",
            request_id,
            context_ms,
            len(query_context),
            top_context_score,
            context_timeout_ms,
        )

        lang = _resolve_language(user_details)
        prompt = _build_stream_prompt(
            lang=lang,
            query=query,
>>>>>>> 7ff3f566494ef823f1013bcd9bc269d63d0fb839
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
                    )

            while True:
                chunk = await queue.get()
                try:
                    if chunk is None:
                        break
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
                buffer        += token
                full_response += token
                while True:
                    min_w, soft_w, max_w = _chunk_thresholds(produced == 0)
                    split_at = _find_split_point(buffer, min_w, soft_w, max_w)
                    if split_at <= 0:
                        break
                    await _enqueue(buffer[:split_at].strip())
                    buffer = buffer[split_at:].lstrip()

<<<<<<< HEAD
=======
                    if first_llm_token_ms is None:
                        first_llm_token_ms = (time.perf_counter() - request_started) * 1000

                    buffer += token
                    full_response += token
                    await _emit_stream_event(
                        sio,
                        sid,
                        "ai-token",
                        {"requestId": request_id, "token": token},
                    )

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
                    await _emit_stream_event(
                        sio,
                        sid,
                        "ai-token",
                        {"requestId": request_id, "token": full_response},
                    )
                    await _enqueue_chunk(full_response)
>>>>>>> 7ff3f566494ef823f1013bcd9bc269d63d0fb839
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
<<<<<<< HEAD
                    await _enqueue(full_response)
                else:
                    logger.warning("[%s] llm_chat also returned empty — using hardcoded fallback", request_id)
                    await _enqueue(_fallback_text(lang))
            except Exception as exc:
                logger.error("[%s] llm_chat fallback also failed: %s — using hardcoded fallback", request_id, exc)
                await _enqueue(_fallback_text(lang))
=======
                    await _emit_stream_event(
                        sio,
                        sid,
                        "ai-token",
                        {"requestId": request_id, "token": full_response},
                    )
                    await _enqueue_chunk(full_response)
            except Exception as exc:
                logger.error("❌ [Stream] request_id=%s LLM fallback failed: %s", request_id, exc, exc_info=True)
                consumer_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await consumer_task
                await _emit_ai_end(success=False, error="llm_fallback_failed")
                total_ms = (time.perf_counter() - request_started) * 1000
                await _emit_latency_metrics(
                    first_llm_token_ms=first_llm_token_ms,
                    first_tts_dispatch_ms=first_tts_dispatch_ms,
                    context_ms=context_ms,
                    total_ms=total_ms,
                    emitted_chunks=emitted_chunks,
                    chars=len(full_response),
                    success=False,
                    error="llm_fallback_failed",
                )
                return False

        if not full_response.strip() and produced_chunks == 0:
            fallback_chunk_text = _fallback_ack_text(lang)
            await _emit_stream_event(
                sio,
                sid,
                "ai-token",
                {"requestId": request_id, "token": fallback_chunk_text},
            )
            await _enqueue_chunk(fallback_chunk_text)
>>>>>>> 7ff3f566494ef823f1013bcd9bc269d63d0fb839

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

<<<<<<< HEAD
        return success
=======
        assistant_message = " ".join(full_response.split()).strip()
        if not assistant_message and fallback_chunk_text:
            assistant_message = fallback_chunk_text
        if assistant_message:
            try:
                await add_message(user_id=user_id, role="assistant", content=assistant_message)
            except Exception as exc:
                logger.warning(
                    "⚠️ [Stream] request_id=%s failed to persist assistant message: %s",
                    request_id,
                    exc,
                )
        await _emit_ai_end(success=tts_success, error=None if tts_success else "tts_stream_failed")
        await _emit_latency_metrics(
            first_llm_token_ms=first_llm_token_ms,
            first_tts_dispatch_ms=first_tts_dispatch_ms,
            context_ms=context_ms,
            total_ms=total_ms,
            emitted_chunks=emitted_chunks,
            chars=len(full_response),
            success=tts_success,
            error=None if tts_success else "tts_stream_failed",
        )
        return tts_success
>>>>>>> 7ff3f566494ef823f1013bcd9bc269d63d0fb839


async def stream_chat_response(
    query: str,
    user_id: str,
    sio: Any,
    sid: str,
    tts_service: Any,
    gender: str = "female",
    voice_name: Optional[str] = None,
    latency_trace: Optional[Dict[str, Any]] = None,
) -> bool:
<<<<<<< HEAD
    return await StreamService().stream_chat_with_tts(
        query=query, user_id=user_id, sio=sio, sid=sid,
        tts_service=tts_service, gender=gender, voice_name=voice_name,
    )
=======
    """Quick helper for stream path with TTS."""
    service = StreamService()
    return await service.stream_chat_with_tts(
        query=query,
        user_id=user_id,
        sio=sio,
        sid=sid,
        tts_service=tts_service,
        gender=gender,
        voice_name=voice_name,
        latency_trace=latency_trace,
    )


async def parallel_chat_execution(
    query: str,
    user_id: str,
    sio: Any,
    sid: str,
    tts_service: Any,
    gender: str = "female",
    voice_name: Optional[str] = None,
    latency_trace: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Run stream (voice path) and chat (PQH→SQH) in parallel.

    Stream stays independent so user gets immediate audio feedback while
    tool orchestration proceeds.
    """
    from .chat_service import chat
    from app.agent.runtime import is_meta_query

    # Meta queries should prioritize factual spoken answer from chat result.
    # This avoids generic stream acknowledgements for status/inventory questions.
    if is_meta_query(query):
        logger.info("📊 Meta query detected — prioritizing factual chat speech path for %s", user_id)
        chat_result = None
        try:
            chat_result = await chat(
                query=query,
                user_id=user_id,
                wait_for_execution=False,
            )
        except Exception as exc:
            logger.error("❌ Chat failed for meta query: %s", exc, exc_info=True)

        spoken_text = _extract_chat_answer_text(chat_result)
        if spoken_text:
            try:
                await tts_service.stream_to_socket(
                    sio=sio,
                    sid=sid,
                    text=spoken_text,
                    voice=voice_name,
                    gender=gender,
                )
                logger.info("🗣️ Meta query spoken response emitted for %s", user_id)
                return {
                    "stream_success": True,
                    "chat_result": chat_result,
                }
            except Exception as exc:
                logger.error("❌ Meta query speech emit failed: %s", exc, exc_info=True)

        # Fallback to regular stream if no factual text available.
        logger.info("↩️ Meta query fallback to regular stream path for %s", user_id)
        stream_ok = await stream_chat_response(
            query=query,
            user_id=user_id,
            sio=sio,
            sid=sid,
            tts_service=tts_service,
            gender=gender,
            voice_name=voice_name,
            latency_trace=latency_trace,
        )
        return {
            "stream_success": stream_ok,
            "chat_result": chat_result,
        }

    async def _independent_stream() -> None:
        try:
            await stream_chat_response(
                query=query,
                user_id=user_id,
                sio=sio,
                sid=sid,
                tts_service=tts_service,
                gender=gender,
                voice_name=voice_name,
                latency_trace=latency_trace,
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
>>>>>>> 7ff3f566494ef823f1013bcd9bc269d63d0fb839
