
import json
from typing import Any, Optional
from app.cache.base_manager import BaseCacheManager
from app.cache.key_config import user_cache_key, user_cache_prefix

class GenericCacheMixin(BaseCacheManager):
    """Generic key-value caching logic"""
    
    async def set_cache(self, user_id: str, key: str, value: Any, expire: Optional[int] = None) -> None:
        """Set a value in the cache"""
        full_key = user_cache_key(user_id, key)
        await self.set(full_key, json.dumps(value), ex=expire)
    
    async def get_cache(self, user_id: str, key: str) -> Optional[Any]:
        """Get a value from the cache"""
        full_key = user_cache_key(user_id, key)
        value = await self.get(full_key)
        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return None
        return None
    
    async def delete_cache(self, user_id: str, key: str) -> None:
        """Delete a value from the cache"""
        full_key = user_cache_key(user_id, key)
        await self.delete(full_key)
    
    async def clear_cache(self, user_id: str) -> None:
        """Clear all cache for a user"""
        pattern = f"{user_cache_prefix(user_id)}*"
        await self._delete_by_pattern(pattern)
