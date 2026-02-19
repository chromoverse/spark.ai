import logging
import time
import lancedb
import pyarrow as pa
import numpy as np
from typing import Optional, List, Any, Dict
from pathlib import Path
from datetime import datetime
from collections import OrderedDict
import uuid


logger = logging.getLogger(__name__)

# In-memory cache
_CHAT_CACHE_MAX_USERS = 50

# --- Schema Definition ---
class UserQuerySchema:
    """Schema for chat messages with embeddings"""
    @staticmethod
    def get_schema():
        return pa.schema([
            pa.field("id", pa.string()),
            pa.field("user_id", pa.string()),
            pa.field("role", pa.string()),
            pa.field("content", pa.string()),
            pa.field("timestamp", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), 1024))  # BGE-M3 dimension
        ])


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
        
        # ✅ In-memory cache for chat history: {user_id: [messages]}
        self._chat_cache: OrderedDict[str, List[Dict[str, Any]]] = OrderedDict()
        
        logger.info(f"🚀 LanceDB initialized at {self.db_path} (persistent table handle)")

    def _init_tables(self):
        """Ensure required tables exist and return persistent handle"""
        existing_tables = self.db.table_names()
        
        if "user_queries" not in existing_tables:
            schema = UserQuerySchema.get_schema()
            self.db.create_table("user_queries", schema=schema)
            logger.info("Created 'user_queries' table")
        
        # ✅ Open ONCE and keep the handle
        return self.db.open_table("user_queries")
    
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
            
            # ✅ Uses persistent table handle
            self._table.add(data)
            
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
        threshold: float = 0.5
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
            
            # ✅ Search with native filter — no post-filtering needed
            results = (
                self._table.search(query_normalized)
                .where(f"user_id = '{user_id}'")
                .limit(limit * 3)
                .to_pandas()
            )
            
            if results.empty:
                logger.debug(f"No search results for user {user_id}")
                return []
            
            logger.info(f"🔍 LanceDB: {len(results)} results for user {user_id}")
            
            # Deduplicate and calculate similarity
            seen_keys = set()
            final_results = []
            
            for _, row in results.iterrows():
                l2_distance = float(row.get("_distance", 2.0))
                cosine_similarity = max(0.0, 1.0 - (l2_distance ** 2) / 2.0)
                
                dedup_key = f"{row['content']}_{row['timestamp']}"
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)
                
                if cosine_similarity >= threshold:
                    final_results.append({
                        "id": row["id"],
                        "role": row["role"],
                        "content": row["content"],
                        "timestamp": row["timestamp"],
                        "_similarity_score": round(cosine_similarity, 4),
                        "_distance": round(l2_distance, 4)
                    })
                
                if len(final_results) >= limit:
                    break
            
            final_results.sort(key=lambda x: x["_similarity_score"], reverse=True)
            
            if final_results:
                logger.info(
                    f"✅ Search found {len(final_results)} results "
                    f"(threshold={threshold}, top_score={final_results[0]['_similarity_score']})"
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