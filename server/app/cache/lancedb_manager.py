import logging
import time
import lancedb
import pyarrow as pa
import numpy as np
from typing import Optional, List, Any, Dict
from pathlib import Path
from datetime import datetime
import uuid


logger = logging.getLogger(__name__)

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
    """LanceDB backend for vector search ONLY"""
    
    _instance: Optional['LanceDBManager'] = None
    _initialized: bool = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        # Prevent re-initialization if already initialized
        if LanceDBManager._initialized:
            return
        LanceDBManager._initialized = True
        
        from app.utils.path_manager import PathManager
        self.path_manager = PathManager()
        self.db_path = self.path_manager.get_user_data_dir() / "db" / "lanceData"
        self.db_path.mkdir(parents=True, exist_ok=True)
        
        self.db = lancedb.connect(str(self.db_path))
        self._init_tables()
        logger.info(f"🚀 LanceDB initialized at {self.db_path}")

    def _init_tables(self):
        """Ensure required tables exist"""
        existing_tables = self.db.table_names()
        
        if "user_queries" not in existing_tables:
            schema = UserQuerySchema.get_schema()
            self.db.create_table("user_queries", schema=schema)
            logger.info("Created 'user_queries' table")

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
            table = self.db.open_table("user_queries")
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
                "vector": vector_normalized  # Store normalized vector
            }]
            
            table.add(data)
            logger.debug(f"✅ Added message {unique_id}: {content[:50]}...")
            return True
        except Exception as e:
            logger.error(f"LanceDB Add Message Error: {e}", exc_info=True)
            return False

    async def get_chat_history(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Retrieve recent chat history"""
        try:
            table = self.db.open_table("user_queries")
            
            # Query without vector search, just filter
            results = table.to_pandas()
            
            # Filter by user_id
            user_messages = results[results['user_id'] == user_id]
            
            if user_messages.empty:
                logger.debug(f"No messages found for user {user_id}")
                return []
            
            # Deduplicate by content+timestamp
            history_dict = {}
            for _, row in user_messages.iterrows():
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
        Semantic search with NORMALIZED VECTORS for cosine similarity
        
        SOLUTION: Normalize both query and stored vectors
        - When vectors are normalized, L2 distance ≈ 2(1 - cosine_similarity)
        - So: cosine_similarity ≈ 1 - (L2_distance / 2)
        """
        try:
            table = self.db.open_table("user_queries")
            
            # NORMALIZE query vector for cosine similarity
            query_np = np.array(query_vector, dtype=np.float32)
            norm = np.linalg.norm(query_np)
            if norm > 0:
                query_normalized = (query_np / norm).tolist()
            else:
                query_normalized = query_vector
            
            # Search with normalized query
            results = (
                table.search(query_normalized)
                .limit(limit * 3)
                .to_pandas()
            )
            
            if results.empty:
                logger.debug(f"No search results for user {user_id}")
                return []
            
            logger.info(f"🔍 LanceDB raw results: {len(results)} rows before filtering")
            
            # Filter by user_id
            user_results = results[results['user_id'] == user_id]
            
            if user_results.empty:
                logger.warning(f"No results after filtering for user {user_id}")
                return []
            
            logger.info(f"📊 After user filter: {len(user_results)} messages")
            
            # Deduplicate and calculate similarity
            seen_keys = set()
            final_results = []
            
            for _, row in user_results.iterrows():
                # With normalized vectors, L2 distance = sqrt(2(1 - cosine_similarity))
                # So: cosine_similarity = 1 - (L2_distance^2 / 2)
                l2_distance = float(row.get("_distance", 2.0))
                
                # Convert L2 distance to cosine similarity
                # For normalized vectors: cos_sim ≈ 1 - (L2^2 / 2)
                cosine_similarity = max(0.0, 1.0 - (l2_distance ** 2) / 2.0)
                
                # Debug logging
                logger.debug(
                    f"Message: '{row['content'][:40]}' | "
                    f"L2 Distance: {l2_distance:.4f} | "
                    f"Cosine Similarity: {cosine_similarity:.4f} | "
                    f"Threshold: {threshold}"
                )
                
                # Dedup key
                dedup_key = f"{row['content']}_{row['timestamp']}"
                if dedup_key in seen_keys:
                    logger.debug(f"  → Skipped (duplicate)")
                    continue
                seen_keys.add(dedup_key)
                
                # Check threshold
                if cosine_similarity >= threshold:
                    final_results.append({
                        "id": row["id"],
                        "role": row["role"],
                        "content": row["content"],
                        "timestamp": row["timestamp"],
                        "_similarity_score": round(cosine_similarity, 4),
                        "_distance": round(l2_distance, 4)
                    })
                    logger.debug(f"  ✅ Added (similarity {cosine_similarity:.4f} >= {threshold})")
                else:
                    logger.debug(f"  ❌ Rejected (similarity {cosine_similarity:.4f} < {threshold})")
                
                if len(final_results) >= limit:
                    break
            
            # Sort by similarity (highest first)
            final_results.sort(key=lambda x: x["_similarity_score"], reverse=True)
            
            if final_results:
                logger.info(
                    f"✅ Search found {len(final_results)} results "
                    f"(threshold={threshold}, top_score={final_results[0]['_similarity_score']})"
                )
            else:
                logger.warning(
                    f"⚠️ No results above threshold {threshold}. "
                    f"Try lowering threshold (e.g., 0.3 or 0.2)."
                )
            
            return final_results[:limit]
            
        except Exception as e:
            logger.error(f"LanceDB Search Error: {e}", exc_info=True)
            return []

    async def clear_user_data(self, user_id: str):
        """Clear all chat messages for user"""
        try:
            table = self.db.open_table("user_queries")
            
            # Delete by filtering
            df = table.to_pandas()
            user_messages = df[df['user_id'] == user_id]
            
            if not user_messages.empty:
                # Get IDs to delete
                ids_to_delete = user_messages['id'].tolist()
                
                # Delete one by one (LanceDB limitation)
                for msg_id in ids_to_delete:
                    table.delete(f"id = '{msg_id}'")
                
                logger.info(f"🗑️ Cleared {len(ids_to_delete)} messages for user {user_id}")
            
            return True
        except Exception as e:
            logger.error(f"LanceDB Clear User Error: {e}", exc_info=True)
            return False

    async def get_table_stats(self) -> Dict[str, Any]:
        """Get statistics"""
        try:
            table = self.db.open_table("user_queries")
            df = table.to_pandas()
            
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
            table = self.db.open_table("user_queries")
            table.compact_files()
            logger.info(f"✨ Compacted user_queries table")
            return True
        except Exception as e:
            logger.error(f"Optimization error: {e}")
            return False