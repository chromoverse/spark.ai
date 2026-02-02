"""
Embedding Worker - Ultra-fast async embedding generation with queue
"""
import asyncio
import logging
from typing import List, Union
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
import numpy as np

from app.ml.model_loader import model_loader
from app.ml.config import WORKER_SETTINGS

logger = logging.getLogger(__name__)

class EmbeddingWorker:
    """Async worker for generating embeddings"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self.executor = ThreadPoolExecutor(
                max_workers=WORKER_SETTINGS["max_workers"],
                thread_name_prefix="embedding_worker"
            )
            self.model = None
            self._initialized = True
            logger.info("✅ EmbeddingWorker initialized")
    
    def _ensure_model_loaded(self):
        """Ensure embedding model is loaded"""
        if self.model is None:
            self.model = model_loader.get_model("embedding")
            if self.model is None:
                self.model = model_loader.load_model("embedding")
            if self.model is None:
                raise RuntimeError("Failed to load embedding model")
    
    def _generate_embeddings_sync(
        self,
        texts: Union[str, List[str]],
        batch_size: int = 32,
        normalize: bool = True
    ) -> np.ndarray:
        """Synchronous embedding generation"""
        self._ensure_model_loaded()
        
        if isinstance(texts, str):
            texts = [texts]
        
        embeddings = self.model.encode(  # type: ignore
            texts,
            batch_size=batch_size,
            show_progress_bar=False,
            normalize_embeddings=normalize
        )
        
        return embeddings
    
    async def generate_embeddings(
        self,
        texts: Union[str, List[str]],
        batch_size: int = 32,
        normalize: bool = True
    ) -> np.ndarray:
        """
        Async embedding generation
        
        Args:
            texts: Single text or list of texts
            batch_size: Batch size for processing
            normalize: Whether to normalize embeddings
            
        Returns:
            numpy array of embeddings
        """
        loop = asyncio.get_event_loop()
        
        embeddings = await loop.run_in_executor(
            self.executor,
            self._generate_embeddings_sync,
            texts,
            batch_size,
            normalize
        )
        
        return embeddings
    
    async def generate_single_embedding(self, text: str, normalize: bool = True) -> List[float]:
        """
        Generate embedding for a single text
        
        Returns:
            List of floats (embedding vector)
        """
        embeddings = await self.generate_embeddings(text, normalize=normalize)
        return embeddings[0].tolist()
    
    async def generate_batch_embeddings(
        self,
        texts: List[str],
        batch_size: int = 32,
        normalize: bool = True
    ) -> List[List[float]]:
        """
        Generate embeddings for multiple texts
        
        Returns:
            List of embedding vectors
        """
        embeddings = await self.generate_embeddings(texts, batch_size, normalize)
        return embeddings.tolist()
    
    def shutdown(self):
        """Shutdown the worker"""
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=True)
            logger.info("✅ EmbeddingWorker shutdown complete")


# Singleton instance
embedding_worker = EmbeddingWorker()


# Helper functions for easy use
async def get_embedding(text: str) -> List[float]:
    """Quick helper to get single embedding"""
    return await embedding_worker.generate_single_embedding(text)


async def get_embeddings(texts: List[str]) -> List[List[float]]:
    """Quick helper to get batch embeddings"""
    return await embedding_worker.generate_batch_embeddings(texts)