"""
Embedding Service - Semantic embeddings with utilities
Single source of truth for all embedding operations
"""
import logging
import numpy as np
from typing import List, Dict, Any, Tuple, Optional

from app.ml import get_embedding, get_embeddings, model_loader, DEVICE

logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Unified embedding service with semantic search capabilities
    Uses ML model loader as foundation
    """
    
    def __init__(self):
        self.model = None
        self._ensure_model_loaded()
    
    def _ensure_model_loaded(self):
        """Ensure embedding model is loaded"""
        if self.model is None:
            self.model = model_loader.get_model("embedding")
            if self.model is None:
                logger.warning("⚠️ Embedding model not loaded, attempting to load...")
                self.model = model_loader.load_model("embedding")
            
            if self.model:
                logger.info("✅ Embedding service ready")
    
    async def embed_single(self, text: str) -> List[float]:
        """
        Generate embedding for single text
        
        Args:
            text: Input text
            
        Returns:
            List of floats (embedding vector)
        
        Usage:
            embedding = await embedding_service.embed_single("Hello world")
        """
        return await get_embedding(text)
    
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts (batch processing)
        
        Args:
            texts: List of input texts
            
        Returns:
            List of embedding vectors
        
        Usage:
            embeddings = await embedding_service.embed_batch(["text1", "text2"])
        """
        return await get_embeddings(texts)
    
    async def similarity(self, text1: str, text2: str) -> float:
        """
        Calculate cosine similarity between two texts
        
        Args:
            text1: First text
            text2: Second text
            
        Returns:
            Similarity score (0-1, higher = more similar)
        
        Usage:
            score = await embedding_service.similarity("I love cats", "I adore felines")
            # Returns: 0.85 (very similar)
        """
        embeddings = await get_embeddings([text1, text2])
        emb1 = np.array(embeddings[0])
        emb2 = np.array(embeddings[1])
        
        similarity = np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2))
        return float(similarity)
    
    async def similarity_detailed(self, text1: str, text2: str) -> Dict[str, Any]:
        """
        Calculate similarity with interpretation
        
        Args:
            text1: First text
            text2: Second text
            
        Returns:
            Dict with score and interpretation
        
        Usage:
            result = await embedding_service.similarity_detailed("cats", "dogs")
            # Returns: {"score": 0.65, "interpretation": "Somewhat similar", ...}
        """
        score = await self.similarity(text1, text2)
        
        # Interpret similarity
        if score > 0.85:
            interpretation = "Very similar"
        elif score > 0.7:
            interpretation = "Similar"
        elif score > 0.5:
            interpretation = "Somewhat similar"
        elif score > 0.3:
            interpretation = "Slightly similar"
        else:
            interpretation = "Not similar"
        
        return {
            "text1": text1,
            "text2": text2,
            "score": round(score, 4),
            "interpretation": interpretation
        }
    
    async def find_most_similar(
        self,
        query: str,
        candidates: List[str],
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Find most similar texts from candidates
        
        Args:
            query: Query text
            candidates: List of candidate texts
            top_k: Number of top results to return
            
        Returns:
            List of dicts with text, score, and rank
        
        Usage:
            results = await embedding_service.find_most_similar(
                "machine learning",
                ["AI", "cooking", "neural networks", "recipe"]
            )
            # Returns: [{"text": "neural networks", "score": 0.89, "rank": 1}, ...]
        """
        if not candidates:
            return []
        
        # Get embeddings
        all_texts = [query] + candidates
        embeddings = await get_embeddings(all_texts)
        
        query_emb = np.array(embeddings[0])
        candidate_embs = np.array(embeddings[1:])
        
        # Calculate similarities
        similarities = np.dot(candidate_embs, query_emb) / (
            np.linalg.norm(candidate_embs, axis=1) * np.linalg.norm(query_emb)
        )
        
        # Sort by similarity (descending)
        sorted_indices = np.argsort(similarities)[::-1]
        
        # Get top k
        top_k = min(top_k, len(candidates))
        results = []
        
        for rank, idx in enumerate(sorted_indices[:top_k], 1):
            results.append({
                "rank": rank,
                "text": candidates[idx],
                "score": round(float(similarities[idx]), 4)
            })
        
        return results
    
    async def semantic_search(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        text_key: str = "text",
        top_k: int = 10,
        threshold: float = 0.5,
    ) -> List[Dict[str, Any]]:
        """
        Semantic search over documents
        
        Args:
            query: Search query
            documents: List of documents (dicts with text_key)
            text_key: Key in document dict containing text
            top_k: Number of results to return
            threshold: Minimum similarity score (0-1)
            
        Returns:
            List of documents with similarity scores
        
        Usage:
            docs = [
                {"id": 1, "text": "Python programming"},
                {"id": 2, "text": "Machine learning"},
            ]
            results = await embedding_service.semantic_search(
                "coding in python",
                docs,
                top_k=5
            )
        """
        if not documents:
            return []
        
        # Extract texts
        texts = [doc.get(text_key, "") for doc in documents]
        
        # Get embeddings
        all_texts = [query] + texts
        embeddings = await get_embeddings(all_texts)
        
        query_emb = np.array(embeddings[0])
        doc_embs = np.array(embeddings[1:])
        
        # Calculate similarities
        similarities = np.dot(doc_embs, query_emb) / (
            np.linalg.norm(doc_embs, axis=1) * np.linalg.norm(query_emb)
        )
        
        # Filter by threshold and sort
        results = []
        for idx, (doc, score) in enumerate(zip(documents, similarities)):
            if score >= threshold:
                result = doc.copy()
                result["score"] = round(float(score), 4)
                result["_rank"] = 0  # Will be set after sorting
                results.append(result)
        
        # Sort by score (descending)
        results.sort(key=lambda x: x["score"], reverse=True)
        
        # Set ranks and limit to top_k
        for rank, result in enumerate(results[:top_k], 1):
            result["_rank"] = rank
        
        return results[:top_k]
    
    async def cluster_texts(
        self,
        texts: List[str],
        n_clusters: int = 3
    ) -> Dict[str, Any]:
        """
        Cluster texts by semantic similarity
        
        Args:
            texts: List of texts to cluster
            n_clusters: Number of clusters
            
        Returns:
            Dict with cluster assignments and centroids
        
        Usage:
            result = await embedding_service.cluster_texts(
                ["cat", "dog", "python", "java", "bird"],
                n_clusters=2
            )
            # Returns: {"clusters": [[0, 1, 4], [2, 3]], ...}
        """
        from sklearn.cluster import KMeans
        
        if len(texts) < n_clusters:
            logger.warning(f"Too few texts ({len(texts)}) for {n_clusters} clusters")
            n_clusters = len(texts)
        
        # Get embeddings
        embeddings = await get_embeddings(texts)
        embeddings_array = np.array(embeddings)
        
        # Perform clustering
        kmeans = KMeans(n_clusters=n_clusters, random_state=42)
        labels = kmeans.fit_predict(embeddings_array)
        
        # Organize by clusters
        clusters = {i: [] for i in range(n_clusters)}
        for idx, label in enumerate(labels):
            clusters[label].append({
                "index": idx,
                "text": texts[idx]
            })
        
        return {
            "n_clusters": n_clusters,
            "clusters": clusters,
            "cluster_sizes": {i: len(items) for i, items in clusters.items()}
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get service status"""
        return {
            "available": self.model is not None,
            "device": DEVICE,
            "dimension": 1024  # BGE-M3 dimension
        }


# Singleton instance
embedding_service = EmbeddingService()


# Convenience functions for common operations
async def get_text_similarity(text1: str, text2: str) -> float:
    """
    Quick similarity check between two texts
    
    Usage:
        score = await get_text_similarity("Hello", "Hi")
    """
    return await embedding_service.similarity(text1, text2)


async def search_similar_texts(query: str, texts: List[str], top_k: int = 5) -> List[Dict]:
    """
    Quick semantic search
    
    Usage:
        results = await search_similar_texts("python", ["java", "python", "ruby"])
    """
    return await embedding_service.find_most_similar(query, texts, top_k)