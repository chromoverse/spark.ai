import json
import logging
import asyncio
import time
import hashlib
import numpy as np
import base64
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, List, Dict, TYPE_CHECKING
from collections import OrderedDict
from app.cache.base_manager import BaseRedisManager

if TYPE_CHECKING:
    from app.cache.lancedb_manager import LanceDBManager
    from app.cache.local_kv_manager import LocalKVManager

logger = logging.getLogger(__name__)
NEPAL_TZ = timezone(timedelta(hours=5, minutes=45))
EMBEDDING_TTL = 86400 * 7
LOCAL_CACHE_SIZE = 500

class ChatCacheMixin(BaseRedisManager):
    """Conversation history and embedding logic"""
    
    _local_emb_cache: OrderedDict = OrderedDict()
    _env: Optional[str] = None  # Cache environment type

    def _init_env(self) -> str:
        """Initialize environment once and cache it"""
        if self._env is None:
            from app.config import settings
            self._env = settings.environment
            logger.info(f"🌍 Environment initialized: {self._env}")
        return self._env
    
    def _is_desktop_env(self) -> bool:
        """Check if running in desktop environment"""
        return self._init_env() == "desktop"

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

    async def add_message(self, user_id: str, role: str, content: str) -> None:
        """
        Add message to BOTH storages:
        1. SQLite (for fast retrieval of chat history)
        2. LanceDB (for semantic search with vectors)
        """
        timestamp = datetime.now(NEPAL_TZ).isoformat()
        message_id = f"{user_id}_{int(time.time() * 1000000)}_{uuid.uuid4().hex[:8]}"
        
        kv_client = self._get_kv_client()
        vector_client = self._get_vector_client()
        
        if kv_client and vector_client:
            from app.services.embedding_services import embedding_service
            try:
                # Generate embedding
                embedding = await embedding_service.embed_single(content)
                
                # 1. Add to SQLite (messages table)
                await kv_client.add_message(user_id, role, content, timestamp, message_id)
                
                # 2. Add to LanceDB (vectors table)
                await vector_client.add_chat_message(user_id, role, content, embedding, timestamp)
                
                logger.debug(f"✅ Message added to both SQLite + LanceDB: [{role}] {content[:50]}...")
                return
            except Exception as e:
                logger.error(f"❌ Error adding message: {e}", exc_info=True)
                return

        # Redis path (production/dev)
        key = f"user:{user_id}:conversation"
        message = {
            "role": role,
            "content": content,
            "timestamp": timestamp
        }
        await self.rpush(key, json.dumps(message))
        asyncio.create_task(self._cache_embedding_with_user(content, user_id))
    
    async def add_messages_batch(
        self, 
        user_id: str, 
        messages: List[tuple[str, str]]
    ) -> int:
        """Add multiple messages efficiently to BOTH storages"""
        if not messages:
            return 0
        
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
        kv_client = self._get_kv_client()
        if kv_client:
            # Desktop: Get from SQLite directly
            return await kv_client.get_messages(user_id, n)

        # Redis Logic (production/dev)
        try:
            key = f"user:{user_id}:conversation"
            messages_raw = await self.lrange(key, -n, -1)
            if not messages_raw:
                return []
            
            messages: List[Dict[str, Any]] = []
            for msg in messages_raw:
                if msg:
                    try:
                        messages.append(json.loads(msg))
                    except json.JSONDecodeError:
                        continue
            
            return messages[::-1]
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
            logger.info(f"🗑️ Cleared messages from both SQLite + LanceDB for {user_id}")
            return

        # Redis path
        key = f"user:{user_id}:conversation"
        await self.delete(key)
    
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

            cache_key = f"user:{user_id}:emb:{text_hash}"
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
        """Batch cache retrieval using pipeline"""
        if not texts:
            return []
        
        try:
            cache_keys = [
                f"user:{user_id}:emb:{self._get_text_hash(text)}" 
                for text in texts
            ]
            
            pipeline = await self.pipeline()
            for key in cache_keys:
                pipeline.get(key)
            
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
                    keys_to_fetch_remote.append(f"user:{user_id}:emb:{text_hash}")
                    remote_indices.append(i)

            if keys_to_fetch_remote:
                pipeline = await self.pipeline()
                for key in keys_to_fetch_remote:
                    pipeline.get(key)
                
                cached_values = await pipeline.execute()
                
                for idx, cached in zip(remote_indices, cached_values):
                    if cached:
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
            
            cache_key = f"user:{user_id}:emb:{text_hash}"
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
            pipeline = await self.pipeline()
            
            for text, embedding in zip(texts, embeddings):
                text_hash = self._get_text_hash(text)
                self._set_local_cache(user_id, text_hash, embedding)
                
                cache_key = f"user:{user_id}:emb:{text_hash}"
                serialized = self._serialize_embedding(embedding)
                pipeline.setex(cache_key, EMBEDDING_TTL, serialized)
            
            await pipeline.execute()
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
        vector_client = self._get_vector_client()
        if vector_client:
            from app.services.embedding_services import embedding_service
            query_vector = await embedding_service.embed_single(query)
            return await vector_client.search_chat_messages(user_id, query_vector, top_k, 0.1)

        # Redis path (production/dev)
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
        pattern = f"user:{user_id}:emb:*"
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
            pattern = f"user:{user_id}:*"
            await self._delete_by_pattern(pattern)
            
            logger.info(f"🗑️ Cleared ALL data for user {user_id}")
            return
        
        # Redis path
        pattern = f"user:{user_id}:*"
        total_deleted = await self._delete_by_pattern(pattern)
        if total_deleted > 0:
            logger.info(f"🗑️ Cleared all data for user {user_id}: {total_deleted} keys")

    async def process_query_and_get_context(
        self, 
        user_id: str, 
        current_query: str
    ) -> tuple[List[Dict[str, Any]], bool]:
        """
        Process query and get context intelligently:
        - Desktop: Use LanceDB vector search directly
        - Production: Use semantic search + fallback to Pinecone
        """
        vector_client = self._get_vector_client()
        
        # Desktop path: Use LanceDB directly
        if vector_client:
            from app.services.embedding_services import embedding_service
            
            # Add message to both storages
            await self.add_message(user_id, "user", current_query)
            
            # Search in LanceDB
            query_vector = await embedding_service.embed_single(current_query)
            context = await vector_client.search_chat_messages(
                user_id, 
                query_vector, 
                limit=10, 
                threshold=0.5
            )
            
            logger.info(f"[Desktop/LanceDB] Found {len(context)} results")
            return context, False
        
        # Production path: Semantic search + Pinecone fallback
        is_pinecone_needed = False
        search_task = asyncio.create_task(
            self.semantic_search_messages(user_id, current_query)
        )
        append_task = asyncio.create_task(
            self._append_message_to_local_and_cloud(user_id, current_query)
        )
        
        context = await search_task
        await append_task
        
        if not context or len(context) == 0:
            from app.db.pinecone import config as pinecone_config
            logger.info("[Pinecone] Low similarity - fetching from Pinecone")
            context = pinecone_config.get_user_all_queries(user_id)
            is_pinecone_needed = True
            return context, is_pinecone_needed

        logger.info(f"[Local] High similarity - using local context ({len(context)} results)")
        return context, is_pinecone_needed
    
    async def _append_message_to_local_and_cloud(self, user_id: str, current_query: str):
        """Append message to local storage and cloud Pinecone"""
        from app.db.pinecone.config import upsert_query
        await self.add_message(user_id, "user", current_query)
        asyncio.create_task(asyncio.to_thread(upsert_query, user_id, current_query))