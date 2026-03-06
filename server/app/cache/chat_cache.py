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
    query_hash,
    user_context_key,
    user_details_key,
    user_embedding_key,
    user_embedding_prefix,
    user_prefix,
    user_recent_messages_key,
)
from app.cache.sync_manager import get_sync_manager
from app.config import settings

if TYPE_CHECKING:
    from app.cache.lancedb_manager import LanceDBManager
    from app.cache.local_kv_manager import LocalKVManager

logger = logging.getLogger(__name__)
NEPAL_TZ = timezone(timedelta(hours=5, minutes=45))
EMBEDDING_TTL = 86400 * 7
LOCAL_CACHE_SIZE = 500
QUERY_CONTEXT_TTL_SECONDS = 20
QUERY_CONTEXT_CACHE_SIZE = 256
DESKTOP_CONTEXT_EMBED_MIN_BUDGET_MS = 500
DESKTOP_CONTEXT_SEARCH_MIN_BUDGET_MS = 300
LEXICAL_FALLBACK_SCAN_LIMIT = 120
LEXICAL_FALLBACK_RECENT_LIMIT = 3
_LEXICAL_TOKEN_RE = re.compile(r"\w+", flags=re.UNICODE)

class ChatCacheMixin(BaseCacheManager):
    """Conversation history and embedding logic"""
    
    _local_emb_cache: OrderedDict = OrderedDict()
    _query_emb_cache: OrderedDict = OrderedDict()  # query text hash → vector
    _query_context_cache: OrderedDict = OrderedDict()  # (user:query) -> (ts, context, pinecone_flag)
    _embedding_warmup_task: Optional[asyncio.Task[Any]] = None
    _QUERY_CACHE_MAX = 400
    _env: Optional[str] = None  # Cache environment type

    def _init_env(self) -> str:
        """Initialize environment once and cache it"""
        if self._env is None:
            from app.config import settings
            self._env = settings.environment
            logger.debug("Environment initialized: %s", self._env)
        return self._env

    @staticmethod
    def _query_context_ttl_seconds() -> int:
        return max(
            1,
            int(getattr(settings, "STREAM_QUERY_CONTEXT_TTL_SECONDS", QUERY_CONTEXT_TTL_SECONDS)),
        )

    @staticmethod
    def _query_context_cache_limit() -> int:
        return max(
            32,
            int(getattr(settings, "STREAM_QUERY_CONTEXT_CACHE_SIZE", QUERY_CONTEXT_CACHE_SIZE)),
        )
    
    def _is_desktop_env(self) -> bool:
        """Check if running in desktop environment"""
        return self._init_env() == "DESKTOP"

    def _get_vector_client(self) -> Optional['LanceDBManager']:
        """Get vector client for desktop"""
        if self._is_desktop_env() and self.vector_client:
            return self.vector_client
        return None
    
    def _get_kv_client(self) -> Optional['LocalKVManager']:
        """Get LocalKV client for desktop - TYPE SAFE"""
        if self._is_desktop_env():
            from app.cache.local_kv_manager import LocalKVManager
            if isinstance(self.client, LocalKVManager):
                return self.client
        return None

    @staticmethod
    def _recent_messages_limit() -> int:
        return max(10, int(getattr(settings, "cache_recent_messages_limit", 50)))

    def _remote_embedding_cache_enabled(self) -> bool:
        # In production Cloudflare path, keep embeddings local-only.
        if settings.environment == "PRODUCTION" and self.is_cloudflare_backend():
            return False
        return True

    async def _read_recent_messages_payload(self, user_id: str) -> tuple[list[dict[str, Any]], float]:
        raw = await self.get(user_recent_messages_key(user_id))
        if not raw:
            return [], 0.0
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [m for m in parsed if isinstance(m, dict)], 0.0
            if isinstance(parsed, dict):
                messages = parsed.get("messages", [])
                if isinstance(messages, list):
                    ts = float(parsed.get("updated_at", 0) or 0)
                    return [m for m in messages if isinstance(m, dict)], ts
        except Exception:
            return [], 0.0
        return [], 0.0

    async def _write_recent_messages_payload(self, user_id: str, messages: list[dict[str, Any]]) -> None:
        payload = {
            "updated_at": time.time(),
            "seq": int(time.time() * 1_000_000),
            "messages": messages[-self._recent_messages_limit() :],
        }
        await self.set(
            user_recent_messages_key(user_id),
            json.dumps(payload, ensure_ascii=False),
        )

    async def add_message(self, user_id: str, role: str, content: str) -> None:
        await self.add_message_with_embedding(
            user_id=user_id,
            role=role,
            content=content,
            embedding=None,
        )

    async def add_message_with_embedding(
        self,
        user_id: str,
        role: str,
        content: str,
        embedding: Optional[List[float]] = None,
    ) -> None:
        """
        Add message to BOTH storages:
        1. SQLite (for fast retrieval of chat history)
        2. LanceDB (for semantic search with vectors)
        """
        timestamp = datetime.now(NEPAL_TZ).isoformat()
        message_id = f"{user_id}_{int(time.time() * 1000000)}_{uuid.uuid4().hex[:8]}"
        await self._ensure_client()
        kv_client = self._get_kv_client()
        vector_client = self._get_vector_client()
        
        if kv_client and vector_client:
            from app.services.embedding_services import embedding_service
            try:
                final_embedding = embedding
                if not final_embedding:
                    final_embedding = await embedding_service.embed_single(content)
                
                # 1. Add to SQLite (messages table)
                await kv_client.add_message(user_id, role, content, timestamp, message_id)
                
                # 2. Add to LanceDB (vectors table)
                await vector_client.add_chat_message(user_id, role, content, final_embedding, timestamp)
                
                logger.debug(f"✅ Message added to both SQLite + LanceDB: [{role}] {content[:50]}...")

                if bool(getattr(settings, "cache_sync_enabled", True)):
                    # Desktop local-first: enqueue core conversation state for cloud sync.
                    try:
                        recent_messages = await kv_client.get_messages(
                            user_id,
                            limit=self._recent_messages_limit(),
                        )
                        asyncio.create_task(
                            get_sync_manager().enqueue_recent_messages(user_id, recent_messages)
                        )
                    except Exception as exc:
                        logger.debug("Failed to enqueue recent_messages sync: %s", exc)
                return
            except Exception as e:
                logger.error(f"❌ Error adding message: {e}", exc_info=True)
                return

        # Remote cache path (production/dev)
        message = {
            "role": role,
            "content": content,
            "timestamp": timestamp
        }
        messages, _ = await self._read_recent_messages_payload(user_id)
        messages.append(message)
        messages = messages[-self._recent_messages_limit() :]
        await self._write_recent_messages_payload(user_id, messages)
        if embedding:
            await self._set_embedding_cache(user_id, content, embedding)
        else:
            asyncio.create_task(self._cache_embedding_with_user(content, user_id))
    
    async def add_messages_batch(
        self, 
        user_id: str, 
        messages: List[tuple[str, str]]
    ) -> int:
        """Add multiple messages efficiently to BOTH storages"""
        if not messages:
            return 0
        await self._ensure_client()
        kv_client = self._get_kv_client()
        vector_client = self._get_vector_client()
        
        if kv_client and vector_client:
            from app.services.embedding_services import embedding_service
            try:
                contents = [content for _, content in messages]
                logger.info(f"Generating {len(contents)} embeddings in batch...")
                embeddings = await embedding_service.embed_batch(contents)
                
                success_count = 0
                for (role, content), embedding in zip(messages, embeddings):
                    timestamp = datetime.now(NEPAL_TZ).isoformat()
                    message_id = f"{user_id}_{int(time.time() * 1000000)}_{uuid.uuid4().hex[:8]}"
                    
                    # 1. SQLite
                    await kv_client.add_message(user_id, role, content, timestamp, message_id)
                    
                    # 2. LanceDB
                    result = await vector_client.add_chat_message(
                        user_id, role, content, embedding, timestamp
                    )
                    if result:
                        success_count += 1
                    await asyncio.sleep(0.001)
                
                logger.info(f"✅ Batch added {success_count}/{len(messages)} messages to both storages")
                return success_count
            except Exception as e:
                logger.error(f"❌ Batch add failed: {e}", exc_info=True)
                return 0
        
        # Redis batch logic
        success_count = 0
        for role, content in messages:
            await self.add_message(user_id, role, content)
            success_count += 1
        return success_count
    
    async def _cache_embedding_with_user(self, text: str, user_id: str) -> None:
        """Background task to cache embedding"""
        try:
            from app.services.embedding_services import embedding_service
            embedding = await embedding_service.embed_single(text)
            await self._set_embedding_cache(user_id, text, embedding)
        except Exception as e:
            logger.debug(f"Failed to cache embedding: {e}")
    
    async def get_last_n_messages(self, user_id: str, n: int = 10) -> List[Dict[str, Any]]:
        """
        Get last N messages from SQLite (FAST, NO VECTORS NEEDED)
        """
        await self._ensure_client()
        kv_client = self._get_kv_client()
        if kv_client:
            # Desktop: Get from SQLite directly
            return await kv_client.get_messages(user_id, n)

        # Remote cache logic (production/dev)
        try:
            messages, _ = await self._read_recent_messages_payload(user_id)
            if not messages:
                return []
            recent = messages[-n:] if len(messages) > n else messages
            return list(reversed(recent))
        except Exception as e:
            self._safe_warn(f"Failed to get messages for user '{user_id}': {e}")
            return []
    
    async def clear_conversation_history(self, user_id: str) -> None:
        """Clear conversation history from BOTH storages"""
        kv_client = self._get_kv_client()
        vector_client = self._get_vector_client()
        
        if kv_client and vector_client:
            # 1. Clear SQLite messages
            await kv_client.clear_messages(user_id)
            # 2. Clear LanceDB vectors
            await vector_client.clear_user_data(user_id)
            if bool(getattr(settings, "cache_sync_enabled", True)):
                try:
                    asyncio.create_task(
                        get_sync_manager().enqueue_delete(
                            "recent_messages",
                            user_recent_messages_key(user_id),
                        )
                    )
                except Exception as exc:
                    logger.debug("Failed to enqueue recent_messages delete sync: %s", exc)
            logger.info(f"🗑️ Cleared messages from both SQLite + LanceDB for {user_id}")
            return

        # Remote path
        await self.delete(user_recent_messages_key(user_id))
    
    def _get_text_hash(self, text: str) -> str:
        """Generate hash for text"""
        return hashlib.md5(text.encode()).hexdigest()
    
    def _serialize_embedding(self, embedding: List[float]) -> str:
        """Binary serialization for faster throughput"""
        try:
            return base64.b64encode(np.array(embedding, dtype=np.float32).tobytes()).decode('ascii')
        except Exception as e:
            logger.error(f"Serialization error: {e}")
            return json.dumps(embedding)

    def _deserialize_embedding(self, data: str) -> Optional[List[float]]:
        """Binary deserialization"""
        try:
            if not data: return None
            if data.startswith("["):
                return json.loads(data)
            return np.frombuffer(base64.b64decode(data), dtype=np.float32).tolist()
        except Exception as e:
            logger.debug(f"Deserialization error: {e}")
            return None

    def _get_local_cache(self, user_id: str, text_hash: str) -> Optional[List[float]]:
        """Get from fast local memory"""
        key = f"{user_id}:{text_hash}"
        if key in self._local_emb_cache:
            self._local_emb_cache.move_to_end(key)
            return self._local_emb_cache[key]
        return None

    def _set_local_cache(self, user_id: str, text_hash: str, embedding: List[float]):
        """Set to fast local memory"""
        key = f"{user_id}:{text_hash}"
        self._local_emb_cache[key] = embedding
        self._local_emb_cache.move_to_end(key)
        if len(self._local_emb_cache) > LOCAL_CACHE_SIZE:
            self._local_emb_cache.popitem(last=False)

    async def _get_embedding_cache(self, user_id: str, text: str) -> Optional[List[float]]:
        """Get cached embedding for text with local and remote tiers"""
        try:
            text_hash = self._get_text_hash(text)
            local = self._get_local_cache(user_id, text_hash)
            if local: return local

            if not self._remote_embedding_cache_enabled():
                return None

            cache_key = user_embedding_key(user_id, text_hash)
            cached = await self.get(cache_key)
            if cached:
                embedding = self._deserialize_embedding(cached)
                if embedding:
                    self._set_local_cache(user_id, text_hash, embedding)
                return embedding
            return None
        except Exception as e:
            logger.debug(f"Failed to get cached embedding: {e}")
            return None
    
    async def _batch_get_embedding_cache(
        self, 
        user_id: str, 
        texts: List[str]
    ) -> List[Optional[List[float]]]:
        """Batch cache retrieval using local memory + backend batch get."""
        if not texts:
            return []
        
        try:
            results: List[Optional[List[float]]] = []
            keys_to_fetch_remote: List[str] = []
            remote_indices: List[int] = []
            
            for i, text in enumerate(texts):
                text_hash = self._get_text_hash(text)
                local = self._get_local_cache(user_id, text_hash)
                if local:
                    results.append(local)
                else:
                    results.append(None)
                    keys_to_fetch_remote.append(user_embedding_key(user_id, text_hash))
                    remote_indices.append(i)

            if keys_to_fetch_remote and self._remote_embedding_cache_enabled():
                cached_values = await self.bulk_get(keys_to_fetch_remote)
                for idx, cached in zip(remote_indices, cached_values):
                    if not cached:
                        continue
                    embedding = self._deserialize_embedding(cached)
                    if embedding:
                        text_hash = self._get_text_hash(texts[idx])
                        self._set_local_cache(user_id, text_hash, embedding)
                        results[idx] = embedding
            
            return results
        except Exception as e:
            logger.debug(f"Failed to batch get cached embeddings: {e}")
            return [None] * len(texts)
    
    async def _set_embedding_cache(self, user_id: str, text: str, embedding: List[float]) -> bool:
        """Cache an embedding with local and remote tiers"""
        try:
            text_hash = self._get_text_hash(text)
            self._set_local_cache(user_id, text_hash, embedding)

            if self._remote_embedding_cache_enabled():
                cache_key = user_embedding_key(user_id, text_hash)
                serialized = self._serialize_embedding(embedding)
                await self.set(cache_key, serialized, ex=EMBEDDING_TTL)
            return True
        except Exception as e:
            logger.debug(f"Failed to cache embedding: {e}")
            return False
    
    async def _batch_set_embedding_cache(
        self,
        user_id: str,
        texts: List[str],
        embeddings: List[List[float]]
    ) -> bool:
        """Batch cache setting using pipeline"""
        if not texts or not embeddings or len(texts) != len(embeddings):
            return False
        
        try:
            batch_payload: List[tuple[str, str, Optional[int]]] = []
            for text, embedding in zip(texts, embeddings):
                text_hash = self._get_text_hash(text)
                self._set_local_cache(user_id, text_hash, embedding)

                if self._remote_embedding_cache_enabled():
                    cache_key = user_embedding_key(user_id, text_hash)
                    serialized = self._serialize_embedding(embedding)
                    batch_payload.append((cache_key, serialized, EMBEDDING_TTL))

            if batch_payload:
                await self.bulk_set(batch_payload)
            return True
        except Exception as e:
            logger.debug(f"Failed to batch cache embeddings: {e}")
            return False
    
    async def get_embeddings_for_messages(
        self,
        user_id: str,
        messages: List[Dict[str, str]],
        text_key: str = "content"
    ) -> List[List[float]]:
        """Get embeddings for messages with batch caching"""
        from app.services.embedding_services import embedding_service
        
        if not messages:
            return []
        
        texts = [msg.get(text_key, "") for msg in messages]
        cached_embeddings = await self._batch_get_embedding_cache(user_id, texts)
        
        embeddings: List[Optional[List[float]]] = []
        texts_to_compute: List[str] = []
        compute_indices: List[int] = []
        
        for i, (text, cached) in enumerate(zip(texts, cached_embeddings)):
            if cached:
                embeddings.append(cached)
            else:
                embeddings.append(None)
                texts_to_compute.append(text)
                compute_indices.append(i)
        
        if texts_to_compute:
            new_embeddings = await embedding_service.embed_batch(texts_to_compute)
            for idx, embedding in zip(compute_indices, new_embeddings):
                embeddings[idx] = embedding
            await self._batch_set_embedding_cache(user_id, texts_to_compute, new_embeddings)
        
        return [emb for emb in embeddings if emb is not None]
    
    async def semantic_search_messages(
        self,
        user_id: str,
        query: str,
        n: int = 500,
        top_k: int = 10,
        threshold: float = 0.5
    ) -> List[Dict[str, Any]]:
        """
        Semantic search from LanceDB ONLY (with vectors)
        """
        await self._ensure_client()
        vector_client = self._get_vector_client()
        if vector_client:
            from app.services.embedding_services import embedding_service
            query_vector = await embedding_service.embed_single(query)
            return await vector_client.search_chat_messages(
                user_id=user_id,
                query_vector=query_vector,
                limit=top_k,
                threshold=threshold,
            )

        # Production path: query Pinecone directly (no local embedding/model load).
        if settings.environment == "PRODUCTION":
            from app.db.pinecone import config as pinecone_config

            try:
                pinecone_rows = await asyncio.to_thread(
                    pinecone_config.search_user_queries,
                    user_id,
                    query,
                    max(1, min(int(top_k), 20)),
                )
            except Exception as exc:
                logger.warning("Pinecone semantic search failed: %s", exc)
                return []

            results: List[Dict[str, Any]] = []
            for row in pinecone_rows:
                try:
                    score = float(row.get("score", 0.0) or 0.0)
                except (TypeError, ValueError):
                    score = 0.0
                if score < threshold:
                    continue

                content = str(row.get("query") or row.get("text") or "").strip()
                if not content:
                    continue

                results.append(
                    {
                        "role": "user",
                        "content": content,
                        "timestamp": row.get("timestamp") or "",
                        "_similarity_score": round(score, 4),
                    }
                )

            if not results and threshold > 0:
                # Keep query-context useful even when score calibration drifts across providers.
                for row in pinecone_rows:
                    content = str(row.get("query") or row.get("text") or "").strip()
                    if not content:
                        continue
                    try:
                        score = float(row.get("score", 0.0) or 0.0)
                    except (TypeError, ValueError):
                        score = 0.0
                    results.append(
                        {
                            "role": "user",
                            "content": content,
                            "timestamp": row.get("timestamp") or "",
                            "_similarity_score": round(score, 4),
                        }
                    )

            results.sort(key=lambda item: float(item.get("_similarity_score", 0.0)), reverse=True)
            results = results[: max(1, int(top_k))]
            top_score = float(results[0].get("_similarity_score", 0.0)) if results else 0.0
            logger.info(
                "🔎 RAG search source=pinecone result_count=%d top_score=%.4f",
                len(results),
                top_score,
            )
            return results

        # Development fallback path: in-memory semantic over recent messages.
        start = time.time()
        messages = await self.get_last_n_messages(user_id, n)
        if not messages:
            return []
        
        logger.info(f"🔍 Searching {len(messages)} messages for '{query[:50]}...'")
        query_task = asyncio.create_task(
            self.get_embeddings_for_messages(user_id, [{"content": query}], "content")
        )
        messages_task = asyncio.create_task(
            self.get_embeddings_for_messages(user_id, messages, "content")
        )
        
        query_embeddings, msg_embeddings = await asyncio.gather(query_task, messages_task)
        if not query_embeddings or not msg_embeddings: return []
        
        query_emb = np.array(query_embeddings[0])
        msg_embs = np.array(msg_embeddings)
        
        query_norm = query_emb / np.linalg.norm(query_emb)
        doc_norms = msg_embs / np.linalg.norm(msg_embs, axis=1, keepdims=True)
        similarities = doc_norms @ query_norm
        
        results: List[Dict[str, Any]] = []
        for idx, (msg, score) in enumerate(zip(messages, similarities)):
            if score >= threshold:
                result = msg.copy()
                result["_similarity_score"] = float(round(float(score), 4))
                results.append(result)
        
        results.sort(key=lambda x: x["_similarity_score"], reverse=True)
        for rank, result in enumerate(results[:top_k], 1):
            result["_rank"] = rank
            
        elapsed = (time.time() - start) * 1000
        logger.info(f"⚡ Search completed in {elapsed:.0f}ms ({len(results)} matches)")
        return results[:top_k]
    
    async def warm_embedding_cache(self, user_id: str, n: int = 500) -> int:
        """Pre-compute and cache embeddings for user's messages"""
        messages = await self.get_last_n_messages(user_id, n)
        if not messages: return 0
        await self.get_embeddings_for_messages(user_id, messages, "content")
        return len(messages)

    async def clear_embedding_cache(self, user_id: str) -> int:
        """Clear all cached embeddings for a user"""
        pattern = f"{user_embedding_prefix(user_id)}*"
        return await self._delete_by_pattern(pattern)

    async def clear_all_user_data(self, user_id: str) -> None:
        """Clear ALL data for a user"""
        kv_client = self._get_kv_client()
        vector_client = self._get_vector_client()
        
        if kv_client and vector_client:
            # Desktop: Clear both storages
            await kv_client.clear_messages(user_id)
            await vector_client.clear_user_data(user_id)
            
            # Clear local embedding cache
            keys_to_remove = [k for k in self._local_emb_cache.keys() if k.startswith(f"{user_id}:")]
            for key in keys_to_remove:
                del self._local_emb_cache[key]
            
            # Clear KV data (user details, generic cache)
            pattern = f"{user_prefix(user_id)}*"
            await self._delete_by_pattern(pattern)

            if bool(getattr(settings, "cache_sync_enabled", True)):
                try:
                    asyncio.create_task(
                        get_sync_manager().enqueue_delete(
                            "recent_messages",
                            user_recent_messages_key(user_id),
                        )
                    )
                    asyncio.create_task(
                        get_sync_manager().enqueue_delete(
                            "user_details",
                            user_details_key(user_id),
                        )
                    )
                except Exception as exc:
                    logger.debug("Failed to enqueue clear_all sync deletes: %s", exc)
            
            logger.info(f"🗑️ Cleared ALL data for user {user_id}")
            return
        
        # Redis path
        pattern = f"{user_prefix(user_id)}*"
        total_deleted = await self._delete_by_pattern(pattern)
        if total_deleted > 0:
            logger.info(f"🗑️ Cleared all data for user {user_id}: {total_deleted} keys")

    def _get_cached_query_embedding(self, text: str) -> Optional[List[float]]:
        """Check in-memory LRU cache for query embedding — ~0ms on hit"""
        text_hash = self._get_text_hash(text)
        if text_hash in self._query_emb_cache:
            self._query_emb_cache.move_to_end(text_hash)
            return self._query_emb_cache[text_hash]
        return None

    def _cache_query_embedding(self, text: str, embedding: List[float]):
        """Cache a query embedding in LRU"""
        text_hash = self._get_text_hash(text)
        self._query_emb_cache[text_hash] = embedding
        self._query_emb_cache.move_to_end(text_hash)
        if len(self._query_emb_cache) > self._QUERY_CACHE_MAX:
            self._query_emb_cache.popitem(last=False)

    @staticmethod
    def _normalize_query(text: str) -> str:
        return " ".join((text or "").strip().lower().split())

    @staticmethod
    def _context_cache_empty_results_enabled() -> bool:
        return bool(getattr(settings, "STREAM_CONTEXT_CACHE_EMPTY_RESULTS", False))

    @staticmethod
    def _tokenize_for_lexical_fallback(text: str) -> set[str]:
        if not text:
            return set()
        tokens: set[str] = set()
        for raw in _LEXICAL_TOKEN_RE.findall(text.lower()):
            token = raw.strip("_")
            if len(token) >= 2:
                tokens.add(token)
        return tokens

    async def _build_lexical_fallback_context(
        self,
        user_id: str,
        query: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        scan_limit = max(LEXICAL_FALLBACK_SCAN_LIMIT, limit * 8)
        messages = await self.get_last_n_messages(user_id, n=scan_limit)
        if not messages:
            return []

        query_tokens = self._tokenize_for_lexical_fallback(query)
        scored: List[Dict[str, Any]] = []
        total = max(1, len(messages))

        for idx, message in enumerate(messages):
            content = str(message.get("content") or "").strip()
            if not content:
                continue

            overlap = 0
            if query_tokens:
                overlap = len(query_tokens & self._tokenize_for_lexical_fallback(content))
                if overlap <= 0:
                    continue

            recency_boost = ((idx + 1) / total) * 0.02
            lexical_score = (overlap / max(1, len(query_tokens))) if query_tokens else 0.0
            score = round(float(min(1.0, lexical_score + recency_boost)), 4)
            scored.append(
                {
                    "id": message.get("id"),
                    "role": message.get("role", "user"),
                    "content": content,
                    "timestamp": message.get("timestamp", ""),
                    "score": score,
                    "_similarity_score": score,
                    "_fallback_source": "lexical_overlap",
                }
            )

        if scored:
            scored.sort(key=lambda item: self._extract_context_score(item), reverse=True)
            return scored[:limit]

        # No lexical overlap: still return recent turns so prompt context isn't empty.
        recent_take = max(1, min(limit, LEXICAL_FALLBACK_RECENT_LIMIT))
        recent_messages = messages[-recent_take:]
        fallback_context: List[Dict[str, Any]] = []
        for rank, message in enumerate(reversed(recent_messages)):
            content = str(message.get("content") or "").strip()
            if not content:
                continue
            score = round(max(0.001, 0.01 - (rank * 0.001)), 4)
            fallback_context.append(
                {
                    "id": message.get("id"),
                    "role": message.get("role", "user"),
                    "content": content,
                    "timestamp": message.get("timestamp", ""),
                    "score": score,
                    "_similarity_score": score,
                    "_fallback_source": "recent_tail",
                }
            )
        return fallback_context

    def _schedule_embedding_warmup_task(self) -> None:
        existing = self.__class__._embedding_warmup_task
        if existing and not existing.done():
            return

        async def _warmup() -> None:
            from app.services.embedding_services import embedding_service

            started = time.perf_counter()
            vector = await embedding_service.embed_single("context retrieval warmup")
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "🔥 Embedding warmup task complete (dim=%d, elapsed_ms=%.0f)",
                len(vector),
                elapsed_ms,
            )

        task = asyncio.create_task(_warmup())
        task.add_done_callback(lambda t: _on_background_done(t, "embedding_warmup_task"))
        self.__class__._embedding_warmup_task = task

    @staticmethod
    def _extract_context_score(item: Dict[str, Any]) -> float:
        score = item.get("score", item.get("_similarity_score", 0))
        try:
            return float(score)
        except (TypeError, ValueError):
            return 0.0

    def _build_query_context_cache_key(
        self,
        user_id: str,
        query: str,
        top_k: int,
        threshold: float,
        fast_lane: bool,
    ) -> str:
        return user_context_key(
            user_id=user_id,
            query_hash=query_hash(query),
            top_k=top_k,
            threshold=threshold,
            fast_lane=fast_lane,
        )

    def _get_query_context_cache(
        self,
        user_id: str,
        query: str,
        top_k: int,
        threshold: float,
        fast_lane: bool,
    ) -> Optional[Tuple[List[Dict[str, Any]], bool]]:
        normalized = self._normalize_query(query)
        if not normalized:
            return None

        key = self._build_query_context_cache_key(
            user_id=user_id,
            query=normalized,
            top_k=top_k,
            threshold=threshold,
            fast_lane=fast_lane,
        )
        item = self._query_context_cache.get(key)
        if not item:
            return None

        ts, context, pinecone_flag = item
        if (time.time() - ts) > self._query_context_ttl_seconds():
            del self._query_context_cache[key]
            return None

        self._query_context_cache.move_to_end(key)
        return context, pinecone_flag

    def _set_query_context_cache(
        self,
        user_id: str,
        query: str,
        context: List[Dict[str, Any]],
        pinecone_flag: bool,
        top_k: int,
        threshold: float,
        fast_lane: bool,
    ) -> None:
        normalized = self._normalize_query(query)
        if not normalized:
            return

        key = self._build_query_context_cache_key(
            user_id=user_id,
            query=normalized,
            top_k=top_k,
            threshold=threshold,
            fast_lane=fast_lane,
        )
        self._query_context_cache[key] = (time.time(), context, pinecone_flag)
        self._query_context_cache.move_to_end(key)
        while len(self._query_context_cache) > self._query_context_cache_limit():
            self._query_context_cache.popitem(last=False)

    async def process_query_and_get_context(
        self, 
        user_id: str, 
        current_query: str,
        budget_ms: Optional[int] = None,
        top_k: int = 10,
        threshold: float = 0.1,
        fast_lane: bool = False,
    ) -> tuple[List[Dict[str, Any]], bool]:
        """
        FAST context retrieval for the current query.
        Also adds the message to storage in the background.
        
        Desktop: LRU cache check → embed (if miss) → LanceDB vector search
        Production: Semantic search + Pinecone fallback
        """
        t0 = time.perf_counter()
        await self._ensure_client()
        vector_client = self._get_vector_client()
        normalized_query = self._normalize_query(current_query)
        default_budget_ms = int(getattr(settings, "STREAM_CONTEXT_TARGET_MS", 100)) if fast_lane else 0
        effective_budget_ms = budget_ms if budget_ms is not None else default_budget_ms
        limit = max(1, top_k)
        deadline = (t0 + (effective_budget_ms / 1000.0)) if effective_budget_ms > 0 else None
        embed_budget_ms = max(1, int(getattr(settings, "STREAM_CONTEXT_EMBED_BUDGET_MS", 35)))
        if fast_lane and vector_client:
            # 35ms is too aggressive for local sentence-transformer inference on CPU.
            embed_budget_ms = max(embed_budget_ms, DESKTOP_CONTEXT_EMBED_MIN_BUDGET_MS)
        search_budget_ms = max(1, int(getattr(settings, "STREAM_CONTEXT_SEARCH_BUDGET_MS", 55)))
        if fast_lane and vector_client:
            # Keep desktop search practical for local LanceDB + pandas conversion costs.
            search_budget_ms = max(search_budget_ms, DESKTOP_CONTEXT_SEARCH_MIN_BUDGET_MS)
        min_results = max(1, int(getattr(settings, "STREAM_CONTEXT_MIN_RESULTS", 3)))
        low_score_threshold = float(getattr(settings, "STREAM_CONTEXT_LOW_SCORE", 0.22))
        cache_empty_results = self._context_cache_empty_results_enabled()
        timeout_stage = "none"
        embed_ms = 0.0
        search_ms = 0.0
        cache_status = "MISS"

        def _remaining_seconds() -> Optional[float]:
            if deadline is None:
                return None
            return max(0.0, deadline - time.perf_counter())

        def _stage_timeout_seconds(stage_budget_ms: int) -> Optional[float]:
            if deadline is None:
                return None
            remaining = _remaining_seconds()
            if remaining is None or remaining <= 0:
                return 0.0
            return min(stage_budget_ms / 1000.0, remaining)

        def _top_score(context_items: List[Dict[str, Any]]) -> float:
            if not context_items:
                return 0.0
            return max(self._extract_context_score(item) for item in context_items)

        def _dedup_and_sort(context_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            dedup: Dict[str, Dict[str, Any]] = {}
            for item in context_items:
                dedup_key = f"{item.get('content') or item.get('query', '')}_{item.get('timestamp', '')}"
                existing = dedup.get(dedup_key)
                if existing is None or self._extract_context_score(item) > self._extract_context_score(existing):
                    dedup[dedup_key] = item
            sorted_results = sorted(
                dedup.values(),
                key=lambda item: self._extract_context_score(item),
                reverse=True,
            )
            return sorted_results[:limit]

        cached_context = self._get_query_context_cache(
            user_id=user_id,
            query=normalized_query,
            top_k=limit,
            threshold=threshold,
            fast_lane=fast_lane,
        )
        if cached_context:
            cache_status = "HIT"
            context, pinecone_flag = cached_context
            if vector_client:
                cached_embedding = self._get_cached_query_embedding(normalized_query)
                write_task = asyncio.create_task(
                    self.add_message_with_embedding(
                        user_id=user_id,
                        role="user",
                        content=current_query,
                        embedding=cached_embedding,
                    )
                )
                write_task.add_done_callback(
                    lambda t: _on_background_done(t, "add_message_with_embedding(cache_hit)")
                )
            else:
                write_task = asyncio.create_task(
                    self._append_message_to_local_and_cloud(user_id, current_query, embedding=None)
                )
                write_task.add_done_callback(
                    lambda t: _on_background_done(t, "append_message_to_local_and_cloud(cache_hit)")
                )
            logger.info(
                "⚡ Context retrieval: total_ms=0 cache_hit=true cache_status=%s embed_ms=0 search_ms=0 "
                "result_count=%d top_score=%.4f timeout_stage=none fast_lane=%s budget_ms=%s",
                cache_status,
                len(context),
                _top_score(context),
                fast_lane,
                effective_budget_ms,
            )
            return context, pinecone_flag
        
        # Desktop path: Use LanceDB directly
        if vector_client:
            from app.services.embedding_services import embedding_service
            
            # ✅ Check LRU cache first — ~0ms on hit
            cached = self._get_cached_query_embedding(normalized_query)
            if cached:
                query_vector = cached
                cache_status = "EMBED_HIT"
            else:
                embed_started = time.perf_counter()
                try:
                    # Use stage budget directly for desktop embedding. Remaining global
                    # budget can be consumed by model warmups and starve retrieval.
                    embed_timeout = (embed_budget_ms / 1000.0) if embed_budget_ms > 0 else None
                    if embed_timeout is not None:
                        query_vector = await asyncio.wait_for(
                            embedding_service.embed_single(current_query),
                            timeout=max(0.01, embed_timeout),
                        )
                    else:
                        query_vector = await embedding_service.embed_single(current_query)
                except asyncio.TimeoutError:
                    logger.warning(
                        "⏱️ Desktop context embedding timed out (stage_budget_ms=%s)",
                        embed_budget_ms,
                    )
                    timeout_stage = "embed"
                    query_vector = None
                except Exception as exc:
                    logger.warning("⚠️ Desktop context embedding failed: %s", exc)
                    timeout_stage = "embed_error"
                    query_vector = None
                embed_ms = (time.perf_counter() - embed_started) * 1000
                if query_vector is not None:
                    self._cache_query_embedding(normalized_query, query_vector)
                cache_status = "EMBED_MISS"
                logger.debug("⚡ Desktop query embedding took %.0fms", embed_ms)

            if query_vector is None:
                # Preserve write path even if retrieval budget was exhausted.
                write_task = asyncio.create_task(
                    self.add_message_with_embedding(
                        user_id=user_id,
                        role="user",
                        content=current_query,
                        embedding=None,
                    )
                )
                write_task.add_done_callback(lambda t: _on_background_done(t, "add_message_with_embedding(no_vector)"))

                # Timeout/error in vector path should not force empty context.
                fallback_context = await self._build_lexical_fallback_context(
                    user_id=user_id,
                    query=current_query,
                    limit=limit,
                )
                if fallback_context:
                    timeout_stage = f"{timeout_stage}_fallback" if timeout_stage != "none" else "lexical_fallback"
                    self._set_query_context_cache(
                        user_id=user_id,
                        query=normalized_query,
                        context=fallback_context,
                        pinecone_flag=False,
                        top_k=limit,
                        threshold=threshold,
                        fast_lane=fast_lane,
                    )
                    elapsed = (time.perf_counter() - t0) * 1000
                    logger.info(
                        "⚡ Context retrieval: total_ms=%.0f cache_hit=false cache_status=%s embed_ms=%.0f "
                        "search_ms=0 result_count=%d top_score=%.4f timeout_stage=%s fast_lane=%s budget_ms=%s",
                        elapsed,
                        cache_status,
                        embed_ms,
                        len(fallback_context),
                        _top_score(fallback_context),
                        timeout_stage,
                        fast_lane,
                        effective_budget_ms,
                    )
                    self._schedule_embedding_warmup_task()
                    return fallback_context, False

                if cache_empty_results and timeout_stage == "none":
                    self._set_query_context_cache(
                        user_id=user_id,
                        query=normalized_query,
                        context=[],
                        pinecone_flag=False,
                        top_k=limit,
                        threshold=threshold,
                        fast_lane=fast_lane,
                    )
                elapsed = (time.perf_counter() - t0) * 1000
                logger.info(
                    "⚡ Context retrieval: total_ms=%.0f cache_hit=false cache_status=%s embed_ms=%.0f "
                    "search_ms=0 result_count=0 top_score=0.0000 timeout_stage=%s fast_lane=%s budget_ms=%s",
                    elapsed,
                    cache_status,
                    embed_ms,
                    timeout_stage,
                    fast_lane,
                    effective_budget_ms,
                )
                self._schedule_embedding_warmup_task()
                return [], False

            # ✅ Persist message in background using SAME embedding (avoids re-embed)
            write_task = asyncio.create_task(
                self.add_message_with_embedding(
                    user_id=user_id,
                    role="user",
                    content=current_query,
                    embedding=query_vector,
                )
            )
            write_task.add_done_callback(lambda t: _on_background_done(t, "add_message_with_embedding"))

            candidate_limit = max(limit, int(getattr(settings, "STREAM_CONTEXT_CANDIDATE_LIMIT", 48)))
            if not fast_lane:
                candidate_limit = max(candidate_limit, limit * 4)

            async def _run_desktop_search(
                *,
                search_limit: int,
                search_threshold: float,
                search_candidate_limit: int,
                stage_budget: int,
            ) -> tuple[List[Dict[str, Any]], bool, float]:
                search_started = time.perf_counter()
                timed_out = False
                try:
                    # Search timeout uses stage budget directly. Remaining global budget is
                    # often exhausted by embedding and can starve retrieval completely.
                    search_timeout = (stage_budget / 1000.0) if stage_budget > 0 else None
                    if search_timeout is not None:
                        search_coro = vector_client.search_chat_messages(
                            user_id=user_id,
                            query_vector=query_vector,
                            limit=search_limit,
                            threshold=search_threshold,
                            candidate_limit=search_candidate_limit,
                        )
                        results = await asyncio.wait_for(
                            search_coro,
                            timeout=max(0.01, search_timeout),
                        )
                    else:
                        search_coro = vector_client.search_chat_messages(
                            user_id=user_id,
                            query_vector=query_vector,
                            limit=search_limit,
                            threshold=search_threshold,
                            candidate_limit=search_candidate_limit,
                        )
                        results = await search_coro
                except asyncio.TimeoutError:
                    timed_out = True
                    results = []
                elapsed_ms = (time.perf_counter() - search_started) * 1000
                return results, timed_out, elapsed_ms

            context, first_timeout, first_ms = await _run_desktop_search(
                search_limit=limit,
                search_threshold=threshold,
                search_candidate_limit=candidate_limit,
                stage_budget=search_budget_ms,
            )
            search_ms += first_ms
            if first_timeout:
                timeout_stage = "search"
                logger.warning(
                    "⏱️ Desktop context search timed out (stage_budget_ms=%s)",
                    search_budget_ms,
                )

            second_pass_allowed = (
                timeout_stage == "none"
                and deadline is not None
                and (_remaining_seconds() or 0.0) > 0.01
            )
            if second_pass_allowed:
                top_score = _top_score(context)
                if len(context) < min_results or top_score < low_score_threshold:
                    relaxed_threshold = max(0.0, min(threshold, low_score_threshold) - 0.05)
                    second_limit = max(limit, min(limit * 2, limit + min_results))
                    second_candidate_limit = max(candidate_limit, second_limit * 4)
                    second_context, second_timeout, second_ms = await _run_desktop_search(
                        search_limit=second_limit,
                        search_threshold=relaxed_threshold,
                        search_candidate_limit=second_candidate_limit,
                        stage_budget=search_budget_ms,
                    )
                    search_ms += second_ms
                    if second_timeout and timeout_stage == "none":
                        timeout_stage = "search_second_pass"
                    context = _dedup_and_sort(context + second_context)
                else:
                    context = _dedup_and_sort(context)
            else:
                context = _dedup_and_sort(context)

            if not context:
                fallback_context = await self._build_lexical_fallback_context(
                    user_id=user_id,
                    query=current_query,
                    limit=limit,
                )
                if fallback_context:
                    context = _dedup_and_sort(fallback_context)
                    timeout_stage = (
                        f"{timeout_stage}_fallback" if timeout_stage != "none" else "lexical_fallback"
                    )
                if timeout_stage.startswith("search"):
                    self._schedule_embedding_warmup_task()

            elapsed = (time.perf_counter() - t0) * 1000
            if context or (cache_empty_results and timeout_stage == "none"):
                self._set_query_context_cache(
                    user_id=user_id,
                    query=normalized_query,
                    context=context,
                    pinecone_flag=False,
                    top_k=limit,
                    threshold=threshold,
                    fast_lane=fast_lane,
                )
            logger.info(
                "⚡ Context retrieval: total_ms=%.0f cache_hit=false cache_status=%s embed_ms=%.0f "
                "search_ms=%.0f result_count=%d top_score=%.4f timeout_stage=%s fast_lane=%s budget_ms=%s",
                elapsed,
                cache_status,
                embed_ms,
                search_ms,
                len(context),
                _top_score(context),
                timeout_stage,
                fast_lane,
                effective_budget_ms,
            )
            return context, False
        
        # Production path: Semantic search + Pinecone fallback — PARALLEL
        is_pinecone_needed = False
        semantic_n = 120 if fast_lane else 500
        search_task = asyncio.create_task(
            self.semantic_search_messages(
                user_id=user_id,
                query=current_query,
                n=semantic_n,
                top_k=limit,
                threshold=threshold,
            )
        )
        # ✅ Fire-and-forget: don't block search on the write
        write_task = asyncio.create_task(
            self._append_message_to_local_and_cloud(user_id, current_query, embedding=None)
        )
        write_task.add_done_callback(lambda t: _on_background_done(t, "append_message_to_local_and_cloud"))
        
        if deadline is not None:
            try:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    raise asyncio.TimeoutError
                context = await asyncio.wait_for(
                    search_task,
                    timeout=remaining,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "⏱️ Production semantic search timed out (%sms), returning empty context",
                    effective_budget_ms,
                )
                timeout_stage = "search"
                context = []
        else:
            context = await search_task
        
        if not context or len(context) == 0:
            fallback_context = await self._build_lexical_fallback_context(
                user_id=user_id,
                query=current_query,
                limit=limit,
            )
            if fallback_context:
                context = _dedup_and_sort(fallback_context)
                timeout_stage = (
                    f"{timeout_stage}_fallback" if timeout_stage != "none" else "lexical_fallback"
                )
                elapsed = (time.perf_counter() - t0) * 1000
                logger.info(
                    "⚡ Context retrieval: total_ms=%.0f cache_hit=false cache_status=MISS embed_ms=0 "
                    "search_ms=%.0f result_count=%d top_score=%.4f timeout_stage=%s fast_lane=%s budget_ms=%s",
                    elapsed,
                    elapsed,
                    len(context),
                    _top_score(context),
                    timeout_stage,
                    fast_lane,
                    effective_budget_ms,
                )
                self._set_query_context_cache(
                    user_id=user_id,
                    query=normalized_query,
                    context=context,
                    pinecone_flag=False,
                    top_k=limit,
                    threshold=threshold,
                    fast_lane=fast_lane,
                )
                return context, False

            if effective_budget_ms > 0 or fast_lane:
                logger.info(
                    "⚡ Context retrieval: budget mode empty result; skipping Pinecone fallback "
                    "(budget_ms=%s, fast_lane=%s)",
                    effective_budget_ms,
                    fast_lane,
                )
                if cache_empty_results and timeout_stage == "none":
                    self._set_query_context_cache(
                        user_id=user_id,
                        query=normalized_query,
                        context=[],
                        pinecone_flag=False,
                        top_k=limit,
                        threshold=threshold,
                        fast_lane=fast_lane,
                    )
                return [], False
            from app.db.pinecone import config as pinecone_config
            logger.info("[Pinecone] Low similarity - fetching from Pinecone")
            context = pinecone_config.get_user_all_queries(user_id)
            is_pinecone_needed = True
            self._set_query_context_cache(
                user_id=user_id,
                query=normalized_query,
                context=context,
                pinecone_flag=is_pinecone_needed,
                top_k=limit,
                threshold=threshold,
                fast_lane=fast_lane,
            )
            return context, is_pinecone_needed

        elapsed = (time.perf_counter() - t0) * 1000
        context = _dedup_and_sort(context)
        logger.info(
            "⚡ Context retrieval: total_ms=%.0f cache_hit=false cache_status=MISS embed_ms=0 search_ms=%.0f "
            "result_count=%d top_score=%.4f timeout_stage=%s fast_lane=%s budget_ms=%s",
            elapsed,
            elapsed,
            len(context),
            _top_score(context),
            timeout_stage,
            fast_lane,
            effective_budget_ms,
        )
        self._set_query_context_cache(
            user_id=user_id,
            query=normalized_query,
            context=context,
            pinecone_flag=is_pinecone_needed,
            top_k=limit,
            threshold=threshold,
            fast_lane=fast_lane,
        )
        return context, is_pinecone_needed
    
    async def _append_message_to_local_and_cloud(
        self,
        user_id: str,
        current_query: str,
        embedding: Optional[List[float]] = None,
    ):
        """Append message to local storage and cloud Pinecone"""
        from app.db.pinecone.config import upsert_query
        await self.add_message_with_embedding(
            user_id=user_id,
            role="user",
            content=current_query,
            embedding=embedding,
        )
        asyncio.create_task(asyncio.to_thread(upsert_query, user_id, current_query))


def _on_background_done(task: asyncio.Task[Any], label: str) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        return
    except Exception as exc:
        logger.debug("Background task '%s' failed: %s", label, exc)
