import json
import logging
import asyncio
import time
import hashlib
import re
import numpy as np
import base64
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, List, Dict, Tuple, TYPE_CHECKING
from collections import OrderedDict
from app.cache.base_manager import BaseCacheManager
from app.cache.key_config import (
    user_embedding_key,
    user_embedding_prefix,
    user_prefix,
    user_recent_messages_key,
    query_hash,
    user_context_key,
)
from app.config import settings

if TYPE_CHECKING:
    from app.cache.lancedb_manager import LanceDBManager
    from app.cache.local_kv_manager import LocalKVManager

logger = logging.getLogger(__name__)

NEPAL_TZ = timezone(timedelta(hours=5, minutes=45))
EMBEDDING_TTL = 86400 * 7        # 7 days
LOCAL_CACHE_SIZE = 500            # max user embeddings held in RAM
QUERY_CACHE_MAX = 400             # max query embeddings in LRU

# Context retrieval tuning
QUERY_CONTEXT_TTL_SECONDS = 20   # seconds before a cached context is stale
QUERY_CONTEXT_CACHE_SIZE = 256   # max distinct (user, query) entries

# Lexical fallback tuning
LEXICAL_FALLBACK_SCAN_LIMIT = 120   # messages scanned for token overlap
LEXICAL_FALLBACK_RECENT_LIMIT = 3   # recent messages returned when no overlap found

# Budget floors for desktop CPU inference (local sentence-transformer is slow)
DESKTOP_EMBED_BUDGET_MS = 15000  # 15 s — first cold call needs ~11 s for model load + inference
DESKTOP_EMBED_WARM_MS   = 3000   # 3 s  — warm inference timeout (model already loaded)
DESKTOP_SEARCH_BUDGET_MS = 1000  # 1 s  — LanceDB local scan

_LEXICAL_TOKEN_RE = re.compile(r"\w+", flags=re.UNICODE)


def _on_background_done(task: asyncio.Task[Any], label: str) -> None:
    """Swallow errors from fire-and-forget tasks so they don't crash the event loop."""
    try:
        task.result()
    except asyncio.CancelledError:
        return
    except Exception as exc:
        logger.debug("Background task '%s' failed: %s", label, exc)


class ChatCacheMixin(BaseCacheManager):
    """
    Desktop-only conversation history + semantic retrieval.

    Storage layout
    ──────────────
    SQLite (LocalKVManager)  – fast sequential message history
    LanceDB (LanceDBManager) – vector index for semantic search

    Every user message is written to BOTH stores.
    Reads prefer the in-process LRU caches, then SQLite/LanceDB on miss.
    """

    # Class-level LRU caches shared across all instances
    _local_emb_cache: OrderedDict = OrderedDict()   # (user_id:text_hash) → vector
    _query_emb_cache: OrderedDict = OrderedDict()   # text_hash → vector (query-side only)
    _query_context_cache: OrderedDict = OrderedDict()  # cache_key → (ts, context)

    # ──────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────

    def _get_vector_client(self) -> Optional["LanceDBManager"]:
        return self.vector_client if self.vector_client else None

    def _get_kv_client(self) -> Optional["LocalKVManager"]:
        from app.cache.local_kv_manager import LocalKVManager
        return self.client if isinstance(self.client, LocalKVManager) else None

    @staticmethod
    def _recent_messages_limit() -> int:
        return max(10, int(getattr(settings, "cache_recent_messages_limit", 50)))

    # ──────────────────────────────────────────────
    # Message write path
    # ──────────────────────────────────────────────

    async def add_message(self, user_id: str, role: str, content: str) -> None:
        await self.add_message_with_embedding(user_id=user_id, role=role, content=content, embedding=None)

    async def add_message_with_embedding(
        self,
        user_id: str,
        role: str,
        content: str,
        embedding: Optional[List[float]] = None,
    ) -> None:
        """
        Write one message to SQLite + LanceDB.
        If no embedding is supplied, one is computed here (blocking, but called in bg tasks).
        """
        await self._ensure_client()
        kv = self._get_kv_client()
        vec = self._get_vector_client()

        if not (kv and vec):
            logger.warning("add_message_with_embedding: storage clients not ready")
            return

        from app.services.embedding_services import embedding_service

        timestamp = datetime.now(NEPAL_TZ).isoformat()
        message_id = f"{user_id}_{int(time.time() * 1_000_000)}_{uuid.uuid4().hex[:8]}"

        # Compute embedding if caller didn't provide one
        if not embedding:
            embedding = await embedding_service.embed_single(content)

        # Persist to SQLite (sequential history)
        await kv.add_message(user_id, role, content, timestamp, message_id)

        # Persist to LanceDB (vector index)
        await vec.add_chat_message(user_id, role, content, embedding, timestamp)

        logger.debug("Message saved to SQLite+LanceDB [%s] %.60s", role, content)

    async def add_messages_batch(
        self,
        user_id: str,
        messages: List[Tuple[str, str]],  # [(role, content), …]
    ) -> int:
        """Batch-write messages with a single embed_batch call for efficiency."""
        if not messages:
            return 0

        await self._ensure_client()
        kv = self._get_kv_client()
        vec = self._get_vector_client()

        if not (kv and vec):
            return 0

        from app.services.embedding_services import embedding_service

        contents = [content for _, content in messages]
        embeddings = await embedding_service.embed_batch(contents)

        count = 0
        for (role, content), emb in zip(messages, embeddings):
            timestamp = datetime.now(NEPAL_TZ).isoformat()
            message_id = f"{user_id}_{int(time.time() * 1_000_000)}_{uuid.uuid4().hex[:8]}"
            await kv.add_message(user_id, role, content, timestamp, message_id)
            ok = await vec.add_chat_message(user_id, role, content, emb, timestamp)
            if ok:
                count += 1
            await asyncio.sleep(0)  # yield between iterations

        logger.info("Batch saved %d/%d messages for %s", count, len(messages), user_id)
        return count

    # ──────────────────────────────────────────────
    # Message read path
    # ──────────────────────────────────────────────

    async def get_last_n_messages(self, user_id: str, n: int = 10) -> List[Dict[str, Any]]:
        """Return the most recent N messages in chronological order (oldest first)."""
        await self._ensure_client()
        kv = self._get_kv_client()
        if kv:
            return await kv.get_messages(user_id, n)
        logger.warning("get_last_n_messages: kv client unavailable")
        return []

    async def clear_conversation_history(self, user_id: str) -> None:
        """Delete all messages from SQLite + LanceDB for this user."""
        kv = self._get_kv_client()
        vec = self._get_vector_client()
        if kv:
            await kv.clear_messages(user_id)
        if vec:
            await vec.clear_user_data(user_id)
        logger.info("Cleared conversation history for %s", user_id)

    # ──────────────────────────────────────────────
    # Embedding cache (in-process LRU)
    # ──────────────────────────────────────────────

    @staticmethod
    def _text_hash(text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()

    @staticmethod
    def _serialize_embedding(embedding: List[float]) -> str:
        """Float32 → base64 string (compact, fast)."""
        return base64.b64encode(np.array(embedding, dtype=np.float32).tobytes()).decode("ascii")

    @staticmethod
    def _deserialize_embedding(data: str) -> Optional[List[float]]:
        """base64 string → float list. Falls back to JSON for legacy values."""
        try:
            if not data:
                return None
            if data.startswith("["):
                return json.loads(data)
            return np.frombuffer(base64.b64decode(data), dtype=np.float32).tolist()
        except Exception:
            return None

    def _get_local_emb(self, user_id: str, text_hash: str) -> Optional[List[float]]:
        key = f"{user_id}:{text_hash}"
        if key in self._local_emb_cache:
            self._local_emb_cache.move_to_end(key)
            return self._local_emb_cache[key]
        return None

    def _set_local_emb(self, user_id: str, text_hash: str, embedding: List[float]) -> None:
        key = f"{user_id}:{text_hash}"
        self._local_emb_cache[key] = embedding
        self._local_emb_cache.move_to_end(key)
        if len(self._local_emb_cache) > LOCAL_CACHE_SIZE:
            self._local_emb_cache.popitem(last=False)

    def _get_query_emb(self, text: str) -> Optional[List[float]]:
        """Query-side LRU (keyed by hash only, not user)."""
        h = self._text_hash(text)
        if h in self._query_emb_cache:
            self._query_emb_cache.move_to_end(h)
            return self._query_emb_cache[h]
        return None

    def _set_query_emb(self, text: str, embedding: List[float]) -> None:
        h = self._text_hash(text)
        self._query_emb_cache[h] = embedding
        self._query_emb_cache.move_to_end(h)
        if len(self._query_emb_cache) > QUERY_CACHE_MAX:
            self._query_emb_cache.popitem(last=False)

    # ──────────────────────────────────────────────
    # Query-context LRU (avoids re-embedding repeated queries)
    # ──────────────────────────────────────────────

    @staticmethod
    def _normalize_query(text: str) -> str:
        return " ".join((text or "").strip().lower().split())

    def _context_cache_key(self, user_id: str, query: str, top_k: int, threshold: float) -> str:
        return user_context_key(
            user_id=user_id,
            query_hash=query_hash(query),
            top_k=top_k,
            threshold=threshold,
            fast_lane=False,  # desktop has no fast-lane distinction
        )

    def _get_context_cache(
        self, user_id: str, query: str, top_k: int, threshold: float
    ) -> Optional[List[Dict[str, Any]]]:
        key = self._context_cache_key(user_id, query, top_k, threshold)
        item = self._query_context_cache.get(key)
        if not item:
            return None
        ts, context = item
        ttl = max(1, int(getattr(settings, "STREAM_QUERY_CONTEXT_TTL_SECONDS", QUERY_CONTEXT_TTL_SECONDS)))
        if (time.time() - ts) > ttl:
            del self._query_context_cache[key]
            return None
        self._query_context_cache.move_to_end(key)
        return context

    def _set_context_cache(
        self, user_id: str, query: str, context: List[Dict[str, Any]], top_k: int, threshold: float
    ) -> None:
        key = self._context_cache_key(user_id, query, top_k, threshold)
        self._query_context_cache[key] = (time.time(), context)
        self._query_context_cache.move_to_end(key)
        limit = max(32, int(getattr(settings, "STREAM_QUERY_CONTEXT_CACHE_SIZE", QUERY_CONTEXT_CACHE_SIZE)))
        while len(self._query_context_cache) > limit:
            self._query_context_cache.popitem(last=False)

    # ──────────────────────────────────────────────
    # Lexical fallback (when vector search is cold / empty)
    # ──────────────────────────────────────────────

    @staticmethod
    def _tokenize(text: str) -> set:
        return {t.strip("_") for t in _LEXICAL_TOKEN_RE.findall(text.lower()) if len(t.strip("_")) >= 2}

    async def _lexical_fallback(self, user_id: str, query: str, limit: int) -> List[Dict[str, Any]]:
        """
        Score recent messages by token overlap with the query.
        Falls back to returning the N most recent messages if no overlap is found.
        """
        messages = await self.get_last_n_messages(user_id, n=max(LEXICAL_FALLBACK_SCAN_LIMIT, limit * 8))
        if not messages:
            return []

        query_tokens = self._tokenize(query)
        scored: List[Dict[str, Any]] = []
        total = max(1, len(messages))

        for idx, msg in enumerate(messages):
            content = str(msg.get("content") or "").strip()
            if not content:
                continue
            overlap = len(query_tokens & self._tokenize(content)) if query_tokens else 0
            if overlap <= 0:
                continue
            # Small recency boost so recent messages rank higher on ties
            recency = ((idx + 1) / total) * 0.02
            lex_score = overlap / max(1, len(query_tokens))
            score = round(min(1.0, lex_score + recency), 4)
            scored.append({**msg, "score": score, "_similarity_score": score, "_fallback_source": "lexical_overlap"})

        if scored:
            scored.sort(key=lambda x: x["score"], reverse=True)
            return scored[:limit]

        # No token overlap — return the most recent few turns so context is never empty
        recent = messages[-LEXICAL_FALLBACK_RECENT_LIMIT:]
        return [
            {**msg, "score": 0.01, "_similarity_score": 0.01, "_fallback_source": "recent_tail"}
            for msg in reversed(recent)
            if str(msg.get("content") or "").strip()
        ]

    # ──────────────────────────────────────────────
    # Dedup + sort helper
    # ──────────────────────────────────────────────

    @staticmethod
    def _top_score(items: List[Dict[str, Any]]) -> float:
        if not items:
            return 0.0
        return max(float(i.get("score", i.get("_similarity_score", 0))) for i in items)

    @staticmethod
    def _dedup_sort(items: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
        """Deduplicate by (content, timestamp), keep highest score, sort descending."""
        seen: Dict[str, Dict[str, Any]] = {}
        for item in items:
            k = f"{item.get('content', '')}_{item.get('timestamp', '')}"
            existing = seen.get(k)
            item_score = float(item.get("score", item.get("_similarity_score", 0)))
            if existing is None or item_score > float(existing.get("score", existing.get("_similarity_score", 0))):
                seen[k] = item
        return sorted(seen.values(), key=lambda x: float(x.get("score", x.get("_similarity_score", 0))), reverse=True)[:limit]

    # ──────────────────────────────────────────────
    # Main entry point
    # ──────────────────────────────────────────────

    async def process_query_and_get_context(
        self,
        user_id: str,
        current_query: str,
        top_k: int = 10,
        threshold: float = 0.1,
    ) -> Tuple[List[Dict[str, Any]], bool]:
        """
        Return relevant context for `current_query` and persist the message in the background.

        Steps
        ─────
        1. Check in-process context LRU → return immediately on hit.
        2. Resolve query embedding (query LRU → embed_single).
        3. LanceDB vector search with generous budgets for CPU inference.
        4. Optional second-pass at relaxed threshold if results are thin.
        5. Lexical fallback if vector search yields nothing.
        6. Cache result, fire-and-forget message write.

        Returns (context_list, False).  The bool is kept for API compatibility.
        """
        t0 = time.perf_counter()
        await self._ensure_client()

        vec = self._get_vector_client()
        if not vec:
            logger.error("process_query_and_get_context: LanceDB client not available")
            return [], False

        normalized = self._normalize_query(current_query)
        limit = max(1, top_k)

        # ── 1. Context LRU hit ──────────────────────────────────────────────
        cached = self._get_context_cache(user_id, normalized, limit, threshold)
        if cached is not None:
            # Fire-and-forget write using cached embedding (avoids re-embed)
            cached_emb = self._get_query_emb(normalized)
            asyncio.create_task(
                self.add_message_with_embedding(user_id, "user", current_query, cached_emb)
            ).add_done_callback(lambda t: _on_background_done(t, "write(context_cache_hit)"))
            logger.info(
                "Context: CACHE HIT  results=%d top_score=%.4f elapsed_ms=0",
                len(cached), self._top_score(cached),
            )
            return cached, False

        # ── 2. Resolve query embedding ──────────────────────────────────────
        from app.services.embedding_services import embedding_service

        query_vector = self._get_query_emb(normalized)
        embed_ms = 0.0

        if query_vector is None:
            embed_start = time.perf_counter()
            try:
                # Cold start (~11 s for model load + first inference) vs warm (~80 ms).
                # Pick the right budget so cold starts don't time out.
                from app.ml.model_loader import model_loader as _ml
                _emb_loaded = _ml.get_model("embedding") is not None
                _budget_ms = DESKTOP_EMBED_WARM_MS if _emb_loaded else DESKTOP_EMBED_BUDGET_MS
                query_vector = await asyncio.wait_for(
                    embedding_service.embed_single(current_query),
                    timeout=_budget_ms / 1000.0,
                )
                self._set_query_emb(normalized, query_vector)
            except asyncio.TimeoutError:
                logger.warning(
                    "Embedding timed out after %dms — falling back to lexical search",
                    _budget_ms,
                )
            except Exception as exc:
                logger.warning("Embedding failed (%s) — falling back to lexical search", exc)
            embed_ms = (time.perf_counter() - embed_start) * 1000

        # ── 3. Lexical fallback if embedding failed ─────────────────────────
        if query_vector is None:
            fallback = await self._lexical_fallback(user_id, current_query, limit)
            asyncio.create_task(
                self.add_message_with_embedding(user_id, "user", current_query, None)
            ).add_done_callback(lambda t: _on_background_done(t, "write(embed_failed)"))
            if fallback:
                self._set_context_cache(user_id, normalized, fallback, limit, threshold)
            elapsed = (time.perf_counter() - t0) * 1000
            logger.info(
                "Context: LEXICAL FALLBACK(embed failed)  results=%d elapsed_ms=%.0f",
                len(fallback), elapsed,
            )
            return fallback, False

        # ── 4. Vector search ────────────────────────────────────────────────
        candidate_limit = max(limit, int(getattr(settings, "STREAM_CONTEXT_CANDIDATE_LIMIT", 48)))

        async def _search(search_threshold: float, cand_limit: int) -> List[Dict[str, Any]]:
            search_start = time.perf_counter()
            try:
                results = await asyncio.wait_for(
                    vec.search_chat_messages(
                        user_id=user_id,
                        query_vector=query_vector,
                        limit=limit,
                        threshold=search_threshold,
                        candidate_limit=cand_limit,
                    ),
                    timeout=DESKTOP_SEARCH_BUDGET_MS / 1000.0,
                )
            except asyncio.TimeoutError:
                logger.warning("Vector search timed out after %dms", DESKTOP_SEARCH_BUDGET_MS)
                results = []
            except Exception as exc:
                logger.warning("Vector search error: %s", exc)
                results = []
            logger.debug("Vector search took %.0fms, got %d results", (time.perf_counter() - search_start) * 1000, len(results))
            return results

        context = await _search(threshold, candidate_limit)

        # ── 5. Second pass at relaxed threshold if results are thin ─────────
        min_results = max(1, int(getattr(settings, "STREAM_CONTEXT_MIN_RESULTS", 3)))
        low_score_threshold = float(getattr(settings, "STREAM_CONTEXT_LOW_SCORE", 0.22))

        if len(context) < min_results or self._top_score(context) < low_score_threshold:
            relaxed = max(0.0, threshold - 0.05)
            second = await _search(relaxed, max(candidate_limit, limit * 4))
            context = self._dedup_sort(context + second, limit)
        else:
            context = self._dedup_sort(context, limit)

        # ── 6. Lexical fallback if vector search is still empty ─────────────
        if not context:
            fallback = await self._lexical_fallback(user_id, current_query, limit)
            if fallback:
                context = self._dedup_sort(fallback, limit)
                logger.info("Context: using LEXICAL FALLBACK after empty vector search")

        # ── 7. Cache result + persist message in background ─────────────────
        if context:
            self._set_context_cache(user_id, normalized, context, limit, threshold)

        asyncio.create_task(
            self.add_message_with_embedding(user_id, "user", current_query, query_vector)
        ).add_done_callback(lambda t: _on_background_done(t, "write(context_retrieved)"))

        elapsed = (time.perf_counter() - t0) * 1000
        logger.info(
            "Context: results=%d top_score=%.4f embed_ms=%.0f total_ms=%.0f",
            len(context), self._top_score(context), embed_ms, elapsed,
        )
        return context, False

    # ──────────────────────────────────────────────
    # Semantic search (direct, no context caching)
    # ──────────────────────────────────────────────

    async def semantic_search_messages(
        self,
        user_id: str,
        query: str,
        top_k: int = 10,
        threshold: float = 0.5,
    ) -> List[Dict[str, Any]]:
        """Direct semantic search — bypasses the context cache."""
        await self._ensure_client()
        vec = self._get_vector_client()
        if not vec:
            return []

        from app.services.embedding_services import embedding_service
        query_vector = await embedding_service.embed_single(query)
        return await vec.search_chat_messages(
            user_id=user_id,
            query_vector=query_vector,
            limit=top_k,
            threshold=threshold,
        )

    # ──────────────────────────────────────────────
    # Housekeeping
    # ──────────────────────────────────────────────

    async def clear_all_user_data(self, user_id: str) -> None:
        """Wipe all storage + in-process caches for this user."""
        kv = self._get_kv_client()
        vec = self._get_vector_client()
        if kv:
            await kv.clear_messages(user_id)
        if vec:
            await vec.clear_user_data(user_id)
        # Evict in-process LRU entries belonging to this user
        for cache in (self._local_emb_cache, self._query_emb_cache):
            stale = [k for k in cache if k.startswith(f"{user_id}:")]
            for k in stale:
                del cache[k]
        logger.info("Cleared all data for user %s", user_id)