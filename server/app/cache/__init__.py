
from app.cache.base_manager import BaseRedisManager
from app.cache.generic_cache import GenericCacheMixin
from app.cache.chat_cache import ChatCacheMixin
from app.cache.user_cache import UserCacheMixin, UserCache, log_cache_performance
from typing import Any, Optional, Dict, List

class RedisManager(GenericCacheMixin, ChatCacheMixin, UserCacheMixin, BaseRedisManager):
    """
    Unified Redis Manager using Mixins.
    Preserves singleton access style.
    """
    pass

# Singleton instance
redis_manager = RedisManager()

# ============ CONVENIENCE FUNCTIONS (backward compatibility) ============

async def load_user(user_id: str) -> Dict[str, Any]:
    return await UserCache.load_user(user_id)

async def get_current_user_cached(user_id: str) -> Dict[str, Any]:
    return await load_user(user_id)

async def invalidate_user_cache(user_id: str):
    await UserCache.invalidate_user(user_id)

async def update_user_quota_flag(user_id: str, provider: str, quota_reached: bool):
    await UserCache.update_user_field(user_id, provider, quota_reached)

async def set_cache(user_id: str, key: str, value: Any, expire: Optional[int] = None) -> None:
    await redis_manager.set_cache(user_id, key, value, expire)

async def get_cache(user_id: str, key: str) -> Optional[Any]:
    return await redis_manager.get_cache(user_id, key)

async def delete_cache(user_id: str, key: str) -> None:
    await redis_manager.delete_cache(user_id, key)

async def clear_cache(user_id: str) -> None:
    await redis_manager.clear_cache(user_id)

async def add_message(user_id: str, role: str, content: str) -> None:
    await redis_manager.add_message(user_id, role, content)

async def get_last_n_messages(user_id: str, n: int = 10) -> List[Dict[str, Any]]:
    return await redis_manager.get_last_n_messages(user_id, n)

async def process_query_and_get_context(user_id: str, query: str) -> tuple[List[Dict[str, Any]], bool]:
    return await redis_manager.process_query_and_get_context(user_id, query)

async def clear_conversation_history(user_id: str) -> None:
    await redis_manager.clear_conversation_history(user_id)

async def set_user_details(user_id: str, details: Dict[str, Any]) -> None:
    await redis_manager.set_user_details(user_id, details)

async def get_user_details(user_id: str) -> Optional[Dict[str, Any]]:
    return await redis_manager.get_user_details(user_id)

async def clear_user_details(user_id: str) -> None:
    await redis_manager.clear_user_details(user_id)

async def update_user_details(user_id: str, details: Dict[str, Any]) -> None:
    await redis_manager.update_user_details(user_id, details)

async def clear_all_user_data(user_id: str) -> None:
    await redis_manager.clear_all_user_data(user_id)

async def get_embeddings_for_messages(user_id: str, messages: List[Dict[str, str]], text_key: str = "content"):
    return await redis_manager.get_embeddings_for_messages(user_id, messages, text_key)

async def semantic_search_messages(user_id: str, query: str, n: int = 500, top_k: int = 10, threshold: float = 0.5):
    return await redis_manager.semantic_search_messages(user_id, query, n, top_k, threshold)

async def warm_embedding_cache(user_id: str, n: int = 500) -> int:
    return await redis_manager.warm_embedding_cache(user_id, n)

async def clear_embedding_cache(user_id: str) -> int:
    return await redis_manager.clear_embedding_cache(user_id)

async def get_embedding_cache_stats(user_id: str) -> Dict[str, Any]:
    # Note: Stats logic was in ChatCacheMixin locally in original, adding here if needed
    # For now, keeping it simple as per original
    return {}
