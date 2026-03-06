import logging
import time
import asyncio
import inspect
import lancedb
import pyarrow as pa
import numpy as np
from typing import Optional, List, Any, Dict
from pathlib import Path
from datetime import datetime
from collections import OrderedDict
import uuid
from app.config import settings
from app.ml.config import MODELS_CONFIG


logger = logging.getLogger(__name__)

# In-memory cache
_CHAT_CACHE_MAX_USERS = 50

# --- Schema Definition ---
class UserQuerySchema:
    """Schema for chat messages with embeddings"""
    @staticmethod
    def get_schema():
        vector_dim = _get_embedding_dimension()
        return pa.schema([
            pa.field("id", pa.string()),
            pa.field("user_id", pa.string()),
            pa.field("role", pa.string()),
            pa.field("content", pa.string()),
            pa.field("timestamp", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), vector_dim))
        ])


def _get_embedding_dimension() -> int:
    config = MODELS_CONFIG.get("embedding", {})
    try:
        return int(config.get("dimension", 1024))
    except Exception:
        return 1024


def _get_table_vector_dimension(table: Any) -> Optional[int]:
    try:
        schema = table.schema
        if schema is None:
            return None
        field = schema.field("vector")
        vector_type = field.type
        # FixedSizeListType exposes list_size.
        if hasattr(vector_type, "list_size"):
            return int(vector_type.list_size)
        return None
    except Exception:
        return None


class LanceDBManager:
    """
    LanceDB backend for vector search ONLY.
    
    OPTIMIZED:
    - Persistent table handle (no per-call open_table)
    - Native LanceDB filters (no full-table pandas loads)
    - In-memory chat history cache
    """
    
    _instance: Optional['LanceDBManager'] = None
    _initialized: bool = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if LanceDBManager._initialized:
            return
        LanceDBManager._initialized = True
        
        from app.utils.path_manager import PathManager
        self.path_manager = PathManager()
        self.db_path = self.path_manager.get_user_data_dir() / "db" / "lanceData"
        self.db_path.mkdir(parents=True, exist_ok=True)
        
        self.db = lancedb.connect(str(self.db_path))
        self._table = self._init_tables()
        self._index_ready = False
        self._ensure_vector_index()
        
        # ✅ In-memory cache for chat history: {user_id: [messages]}
        self._chat_cache: OrderedDict[str, List[Dict[str, Any]]] = OrderedDict()
        
        logger.info(f"🚀 LanceDB initialized at {self.db_path} (persistent table handle)")

    def _init_tables(self):
        """Ensure required tables exist and return persistent handle"""
        existing_tables = self.db.table_names()
        expected_dim = _get_embedding_dimension()
        
        if "user_queries" not in existing_tables:
            schema = UserQuerySchema.get_schema()
            self.db.create_table("user_queries", schema=schema)
            logger.info("Created 'user_queries' table")

        table = self.db.open_table("user_queries")
        existing_dim = _get_table_vector_dimension(table)
        if existing_dim is not None and existing_dim != expected_dim:
            logger.warning(
                "LanceDB vector dimension mismatch (table=%s, expected=%s). Recreating table.",
                existing_dim,
                expected_dim,
            )
            schema = UserQuerySchema.get_schema()
            self.db.create_table("user_queries", schema=schema, mode="overwrite")
            table = self.db.open_table("user_queries")

        # ✅ Open ONCE and keep the handle
        return table

    def _ensure_vector_index(self):
        """
        Best-effort ANN index setup for faster vector retrieval.
        Falls back silently when index APIs differ by LanceDB version.
        """
        if self._index_ready:
            return

        def _create() -> None:
            try:
                if hasattr(self._table, "count_rows") and int(self._table.count_rows()) == 0:
                    logger.debug("LanceDB index deferred: table is empty")
                    return
            except Exception:
                # Keep going even if row counting is unavailable on this version.
                pass

            # Build kwargs from runtime signature so we don't pass unsupported args.
            params = set(inspect.signature(self._table.create_index).parameters)
            kwargs: Dict[str, Any] = {}
            if "vector_column_name" in params:
                kwargs["vector_column_name"] = "vector"
            if "metric" in params:
                kwargs["metric"] = "cosine"
            elif "distance_type" in params:
                kwargs["distance_type"] = "cosine"
            if "index_type" in params:
                # Avoid PQ training requirements for small local datasets.
                kwargs["index_type"] = "IVF_FLAT"
            if "replace" in params:
                kwargs["replace"] = False

            try:
                self._table.create_index(**kwargs)
                return
            except TypeError:
                # Some versions reject a subset of kwargs (for example replace).
                kwargs.pop("replace", None)
                self._table.create_index(**kwargs)
                return
            except Exception as exc:
                if "already exists" in str(exc).lower():
                    return
                raise

        try:
            _create()
            self._index_ready = True
            logger.info("✅ LanceDB vector index ready")
        except Exception as exc:
            logger.warning("⚠️ LanceDB index setup skipped: %s", exc)
    
    def _invalidate_cache(self, user_id: str):
        """Invalidate chat cache for user"""
        if user_id in self._chat_cache:
            del self._chat_cache[user_id]
    
    def _set_cache(self, user_id: str, messages: List[Dict[str, Any]]):
        """Store in LRU cache"""
        self._chat_cache[user_id] = messages
        self._chat_cache.move_to_end(user_id)
        while len(self._chat_cache) > _CHAT_CACHE_MAX_USERS:
            self._chat_cache.popitem(last=False)

    async def ping(self):
        """Health check"""
        return True

    async def add_chat_message(
        self, 
        user_id: str, 
        role: str, 
        content: str, 
        vector: List[float], 
        timestamp: str
    ):
        """Add chat message with embedding - NORMALIZED"""
        try:
            unique_id = f"{user_id}_{int(time.time() * 1000000)}_{uuid.uuid4().hex[:8]}"
            
            # NORMALIZE vector for cosine similarity
            vector_np = np.array(vector, dtype=np.float32)
            norm = np.linalg.norm(vector_np)
            if norm > 0:
                vector_normalized = (vector_np / norm).tolist()
            else:
                vector_normalized = vector
            
            data = [{
                "id": unique_id,
                "user_id": user_id,
                "role": role,
                "content": content,
                "timestamp": timestamp,
                "vector": vector_normalized
            }]
            
            # ✅ Uses persistent table handle, off event loop thread
            await asyncio.to_thread(self._table.add, data)
            if not self._index_ready:
                self._ensure_vector_index()
            
            # ✅ Invalidate cache on write
            self._invalidate_cache(user_id)
            
            logger.debug(f"✅ Added message {unique_id}: {content[:50]}...")
            return True
        except Exception as e:
            logger.error(f"LanceDB Add Message Error: {e}", exc_info=True)
            return False

    async def get_chat_history(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Retrieve recent chat history.
        
        OPTIMIZED: 
        - In-memory cache check first
        - Uses native LanceDB filter instead of loading entire table
        """
        try:
            # ✅ Check cache first (sub-microsecond)
            if user_id in self._chat_cache:
                cached = self._chat_cache[user_id]
                self._chat_cache.move_to_end(user_id)
                result = cached[-limit:] if len(cached) > limit else cached
                logger.debug(f"⚡ LanceDB cache HIT: {len(result)} messages for {user_id}")
                return result
            
            # ✅ Use native filter — NOT table.to_pandas() which loads everything
            results = (
                self._table.search()
                .where(f"user_id = '{user_id}'")
                .select(["id", "role", "content", "timestamp"])
                .limit(limit * 5)  # over-fetch to allow dedup
                .to_pandas()
            )
            
            if results.empty:
                logger.debug(f"No messages found for user {user_id}")
                return []
            
            # Deduplicate by content+timestamp
            history_dict = {}
            for _, row in results.iterrows():
                key = f"{row['content']}_{row['timestamp']}"
                if key not in history_dict:
                    history_dict[key] = {
                        "id": row["id"],
                        "role": row["role"],
                        "content": row["content"],
                        "timestamp": row["timestamp"]
                    }
            
            history = list(history_dict.values())
            history.sort(key=lambda x: x["timestamp"])
            result = history[-limit:] if len(history) > limit else history
            
            # ✅ Store in cache
            self._set_cache(user_id, result)
            
            logger.debug(f"📜 Retrieved {len(result)} messages for {user_id}")
            return result
            
        except Exception as e:
            logger.error(f"LanceDB Get History Error: {e}", exc_info=True)
            return []

    async def search_chat_messages(
        self, 
        user_id: str, 
        query_vector: List[float], 
        limit: int = 10, 
        threshold: float = 0.5,
        candidate_limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Semantic search with NORMALIZED VECTORS for cosine similarity.
        
        OPTIMIZED: Uses persistent table handle.
        """
        try:
            # NORMALIZE query vector
            query_np = np.array(query_vector, dtype=np.float32)
            norm = np.linalg.norm(query_np)
            if norm > 0:
                query_normalized = (query_np / norm).tolist()
            else:
                query_normalized = query_vector
            query_normalized_np = np.array(query_normalized, dtype=np.float32)
            
            def _run_search() -> List[Dict[str, Any]]:
                default_candidate_limit = int(getattr(settings, "STREAM_CONTEXT_CANDIDATE_LIMIT", 48))
                configured = max(limit, default_candidate_limit)
                final_candidate_limit = candidate_limit if candidate_limit is not None else configured
                final_candidate_limit = max(limit, min(256, final_candidate_limit))
                df = (
                    self._table.search(query_normalized)
                    .where(f"user_id = '{user_id}'")
                    .limit(final_candidate_limit)
                    .to_pandas()
                )
                if df.empty:
                    return []
                return [
                    {
                        "id": row["id"],
                        "role": row["role"],
                        "content": row["content"],
                        "timestamp": row["timestamp"],
                        "vector": row.get("vector", []),
                        "_distance": float(row.get("_distance", 2.0)),
                    }
                    for _, row in df.iterrows()
                ]

            rows = await asyncio.to_thread(_run_search)

            if not rows:
                logger.debug(f"No search results for user {user_id}")
                return []
            
            logger.info(f"🔍 LanceDB: {len(rows)} results for user {user_id}")
            
            # Deduplicate and rerank by exact cosine score from stored vectors.
            seen_keys = set()
            final_results = []
            
            for row in rows:
                l2_distance = float(row.get("_distance", 2.0))
                stored_vec = row.get("vector")
                cosine_similarity = max(0.0, 1.0 - (l2_distance ** 2) / 2.0)
                if stored_vec is not None:
                    try:
                        stored_np = np.asarray(stored_vec, dtype=np.float32)
                        if stored_np.size > 0:
                            stored_norm = np.linalg.norm(stored_np)
                        else:
                            stored_norm = 0.0
                        if stored_norm > 0.0:
                            stored_np = stored_np / stored_norm
                            cosine_similarity = float(np.dot(query_normalized_np, stored_np))
                            cosine_similarity = max(0.0, min(1.0, cosine_similarity))
                    except Exception:
                        # Keep distance-derived similarity fallback.
                        pass
                
                dedup_key = f"{row['content']}_{row['timestamp']}"
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)
                
                if cosine_similarity >= threshold:
                    score = round(cosine_similarity, 4)
                    final_results.append({
                        "id": row["id"],
                        "role": row["role"],
                        "content": row["content"],
                        "timestamp": row["timestamp"],
                        "score": score,
                        "_similarity_score": score,
                        "_distance": round(l2_distance, 4)
                    })
            
            final_results.sort(key=lambda x: x["score"], reverse=True)
            
            if final_results:
                logger.info(
                    f"✅ Search found {len(final_results)} results "
                    f"(threshold={threshold}, top_score={final_results[0]['score']})"
                )
            else:
                logger.warning(
                    f"⚠️ No results above threshold {threshold}."
                )
            
            return final_results[:limit]
            
        except Exception as e:
            logger.error(f"LanceDB Search Error: {e}", exc_info=True)
            return []

    async def clear_user_data(self, user_id: str):
        """Clear all chat messages for user"""
        try:
            # ✅ Single SQL-like delete — no pandas load + one-by-one delete
            self._table.delete(f"user_id = '{user_id}'")
            
            # ✅ Invalidate cache
            self._invalidate_cache(user_id)
            
            logger.info(f"🗑️ Cleared all messages for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"LanceDB Clear User Error: {e}", exc_info=True)
            return False

    async def get_table_stats(self) -> Dict[str, Any]:
        """Get statistics"""
        try:
            df = self._table.to_pandas()
            return {
                "total_messages": len(df),
                "unique_users": df["user_id"].nunique() if not df.empty else 0
            }
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {}

    async def compact_and_optimize(self):
        """Compact tables"""
        try:
            self._table.compact_files()
            logger.info(f"✨ Compacted user_queries table")
            return True
        except Exception as e:
            logger.error(f"Optimization error: {e}")
            return False
