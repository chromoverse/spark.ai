from pinecone import ( 
    Pinecone,
    IndexEmbed,
    CloudProvider,
    AwsRegion,
    Metric,
)
from app.config import settings
from typing import Optional, Dict, Any, List
import hashlib
import time
from datetime import datetime, timezone, timedelta
from app.utils.extract_keywords import extract_keywords


class PineconeService:
    """
    Singleton service for managing Pinecone vector database operations.
    Automatically initializes on first use.
    """
    _instance: Optional['PineconeService'] = None
    _initialized: bool = False
    
    NEPAL_TZ = timezone(timedelta(hours=5, minutes=45))
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        # Only initialize once
        if not self._initialized:
            self._setup_client()
            self._setup_index()
            PineconeService._initialized = True
    
    def _setup_client(self):
        """Initialize Pinecone client"""
        self.client = Pinecone(api_key=settings.pinecone_api_key)
        self.index_name = settings.pinecone_index_name
        self.namespace = settings.pinecone_metadata_namespace
    
    def _setup_index(self):
        """Setup or create Pinecone index"""
        if not self.client.has_index(self.index_name):
            print(f"No index named {self.index_name} found. Creating a new index...")
            self.client.create_index_for_model(
                name=self.index_name,
                cloud=CloudProvider.AWS,
                region=AwsRegion.US_EAST_1,
                embed=IndexEmbed(
                    model="llama-text-embed-v2",
                    metric=Metric.COSINE,
                    field_map={"text": "text"}
                )
            )
            print("⏳ Waiting for index to be ready...")
            time.sleep(10)
        else:
            print(f"✅ Index already exists! named {self.index_name}")
        
        self.index = self.client.Index(self.index_name)
    
    @staticmethod
    def generate_stable_id(user_id: str, query: str) -> str:
        """
        Generate a consistent ID using MD5 hash.
        Same input will ALWAYS produce the same ID.
        """
        content = f"{user_id}:{query}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def get_embedding(self, text: str) -> List[float]:
        """
        Get embedding for text using Pinecone's inference API.
        """
        try:
            response = self.client.inference.embed(
                model="llama-text-embed-v2",
                inputs=[text],
                parameters={"input_type": "passage"}
            )
            return response.data[0].values
        except Exception as e:
            print(f"❌ Embedding failed: {e}")
            raise
    
    def upsert_query(self, user_id: str, query: str) -> None:
        """
        Upsert a user query into the Pinecone index.
        Uses stable ID so duplicate queries update instead of creating new records.
        """
        record_id = self.generate_stable_id(user_id, query)
        
        try:
            embedding = self.get_embedding(query)
            
            self.index.upsert(
                vectors=[
                    {
                        "id": record_id,
                        "values": embedding,
                        "metadata": {
                            "user_id": user_id,
                            "query": query,
                            "timestamp": datetime.now(self.NEPAL_TZ).isoformat()
                        }
                    }
                ],
                namespace=self.namespace
            )
            print(f"✅ Upserted query for {user_id}: '{query[:50]}...' (ID: {record_id[:8]}...)")
        except Exception as e:
            print(f"[pinecone] Upsert failed: {e}")
    
    def search_user_queries(self, user_id: str, search_text: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Search for similar queries for a specific user.
        """
        try:
            cleaned_text = extract_keywords(search_text)
            print(f"cleaned text for sent $ {search_text} : {cleaned_text}")
            
            embedding = self.get_embedding(cleaned_text)
            
            results = self.index.query(
                vector=embedding,
                top_k=top_k,
                namespace=self.namespace,
                filter={"user_id": user_id},
                include_metadata=True
            )
            
            matches = getattr(results, 'matches', [])
            
            return [
                {
                    "id": match.id,
                    "score": match.score,
                    "query": match.metadata.get("query", "") if match.metadata else "",
                    "user_id": match.metadata.get("user_id", "") if match.metadata else "",
                    "timestamp": match.metadata.get("timestamp", 0) if match.metadata else 0
                }
                for match in matches
            ]
        except Exception as e:
            print(f"❌ Search failed: {e}")
            return []
    
    def get_user_all_queries(self, user_id: str, top_k: int = 10) -> List[Dict[str, str]]:
        """
        Get all queries for a specific user.
        Uses a generic search term to retrieve all records.
        """
        try:
            embedding = self.get_embedding("all queries")
            
            results = self.index.query(
                vector=embedding,
                top_k=top_k,
                namespace=self.namespace,
                filter={"user_id": user_id},
                include_metadata=True
            )
            
            matches = getattr(results, 'matches', [])
            
            extracted_data = []
            
            for match in matches:
                if match.metadata:
                    item = {
                        'query': match.metadata.get('query', ''),
                        'timestamp': match.metadata.get('timestamp', 0),
                        'user_id': match.metadata.get('user_id', ''),
                        'score': match.score if hasattr(match, 'score') else 0.0,
                        'id': match.id if hasattr(match, 'id') else ''
                    }
                    extracted_data.append(item)
            
            return extracted_data
        except Exception as e:
            print(f"❌ Failed to get queries: {e}")
            return []
    
    def delete_user_query(self, user_id: str, query: str) -> bool:
        """
        Delete a specific query by generating its stable ID.
        """
        try:
            record_id = self.generate_stable_id(user_id, query)
            self.index.delete(
                ids=[record_id],
                namespace=self.namespace
            )
            print(f"🗑️ Deleted query for {user_id}: '{query[:50]}...'")
            return True
        except Exception as e:
            print(f"❌ Delete failed: {e}")
            return False
    
    def delete_user_all_queries(self, user_id: str) -> bool:
        """
        Delete all queries for a specific user.
        """
        try:
            self.index.delete(
                filter={"user_id": user_id},
                namespace=self.namespace
            )
            print(f"🗑️ Deleted all queries for {user_id}")
            return True
        except Exception as e:
            print(f"❌ Delete failed: {e}")
            return False
    
    def get_index_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the index.
        """
        try:
            stats = self.index.describe_index_stats()
            return stats  # type: ignore
        except Exception as e:
            print(f"❌ Failed to get stats: {e}")
            return {}


# Convenience function to get the singleton instance
def get_pinecone_service() -> PineconeService:
    """Get or create the PineconeService singleton instance"""
    return PineconeService()


# For backward compatibility, you can keep module-level functions
pinecone_service = get_pinecone_service()

# Export functions for backward compatibility
upsert_query = pinecone_service.upsert_query
search_user_queries = pinecone_service.search_user_queries
get_user_all_queries = pinecone_service.get_user_all_queries
delete_user_query = pinecone_service.delete_user_query
delete_user_all_queries = pinecone_service.delete_user_all_queries
get_index_stats = pinecone_service.get_index_stats