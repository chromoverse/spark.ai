
import json
import logging
from datetime import datetime, timedelta
from bson import ObjectId
from typing import Any, Optional, Dict, Tuple
from app.cache.base_manager import BaseRedisManager
from app.utils.serialize_mongo_doc import serialize_doc

logger = logging.getLogger(__name__)

class UserCacheMixin(BaseRedisManager):
    """User-specific Redis operations"""

    async def set_user_details(self, user_id: str, details: Dict[str, Any]) -> None:
        """Set user details"""
        key = f"user:{user_id}:details"
        await self.set(key, json.dumps(details))
    
    async def get_user_details(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user details"""
        key = f"user:{user_id}:details"
        details = await self.get(key)
        if details:
            try:
                return json.loads(details)
            except json.JSONDecodeError:
                return None
        return None
    
    async def clear_user_details(self, user_id: str) -> None:
        """Clear user details"""
        key = f"user:{user_id}:details"
        await self.delete(key)
    
    async def update_user_details(self, user_id: str, details: Dict[str, Any]) -> None:
        """Update user details (merge with existing)"""
        existing_details = await self.get_user_details(user_id)
        if existing_details is None:
            await self.set_user_details(user_id, details)
        else:
            existing_details.update(details)
            await self.set_user_details(user_id, existing_details)

class UserCache:
    """
    Three-tier caching strategy for user data.
    Consolidated from load_user variants.
    """
    
    _memory_cache: Dict[str, Tuple[Dict[str, Any], datetime]] = {}
    MEMORY_TTL_SECONDS = 60
    
    @classmethod
    async def get_user(cls, user_id: str) -> Optional[Dict[str, Any]]:
        from app.cache import redis_manager
        now = datetime.utcnow()
        
        if user_id in cls._memory_cache:
            details, cached_at = cls._memory_cache[user_id]
            if now - cached_at < timedelta(seconds=cls.MEMORY_TTL_SECONDS):
                logger.debug(f"⚡ Memory cache HIT for user {user_id}")
                return details
            del cls._memory_cache[user_id]
        
        logger.debug(f"🔍 Memory cache MISS, checking Redis for user {user_id}")
        details = await redis_manager.get_user_details(user_id)
        
        if details:
            cls._memory_cache[user_id] = (details, now)
            logger.debug(f"📦 Redis cache HIT for user {user_id}")
            return details
        return None
    
    @classmethod
    async def load_user(cls, user_id: str) -> Dict[str, Any]:
        if not user_id or user_id in ["null", "undefined"]:
            return {}
        
        cached_user = await cls.get_user(user_id)
        if cached_user is not None:
            return cached_user
        
        logger.info(f"💾 Database query for user {user_id}")
        try:
            from app.db.mongo import get_db
            db = get_db()
            details = await db.users.find_one({"_id": ObjectId(user_id)})
            
            if not details:
                return {}
            
            details = serialize_doc(details)
            from app.cache import redis_manager
            await redis_manager.set_user_details(user_id, details)
            cls._memory_cache[user_id] = (details, datetime.utcnow())
            
            return details
        except Exception as e:
            logger.error(f"❌ Failed to load user {user_id}: {e}", exc_info=True)
            return {}
    
    @classmethod
    async def invalidate_user(cls, user_id: str):
        if user_id in cls._memory_cache:
            del cls._memory_cache[user_id]
        from app.cache import redis_manager
        await redis_manager.clear_user_details(user_id)
        logger.info(f"🧹 Cache cleared for user {user_id}")

    @classmethod
    async def update_user_field(cls, user_id: str, field: str, value: Any):
        if user_id in cls._memory_cache:
            details, cached_at = cls._memory_cache[user_id]
            details[field] = value
            cls._memory_cache[user_id] = (details, cached_at)
        
        from app.cache import redis_manager
        redis_details = await redis_manager.get_user_details(user_id)
        if redis_details:
            redis_details[field] = value
            await redis_manager.set_user_details(user_id, redis_details)

    @classmethod
    def get_cache_stats(cls) -> Dict[str, Any]:
        return {
            "memory_cached_users": len(cls._memory_cache),
            "memory_ttl_seconds": cls.MEMORY_TTL_SECONDS,
            "cached_user_ids": list(cls._memory_cache.keys())
        }

def log_cache_performance():
    stats = UserCache.get_cache_stats()
    logger.info(f"📊 User Cache Stats: {stats['memory_cached_users']} users in memory")
    return stats
