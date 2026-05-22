import asyncio
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

class ResourceLockRegistry:
    """
    Registry for fine-grained resource locks keyed by (user_id, resource_key).
    Prevents parallel jobs from deadlocking or resource collisions.
    """
    def __init__(self):
        # Maps user_id -> resource_key -> asyncio.Lock
        self._locks: Dict[str, Dict[str, asyncio.Lock]] = {}
        self._global_lock = asyncio.Lock()

    def get_lock(self, user_id: str, resource_key: str) -> asyncio.Lock:
        """Get or create a Lock for the resource_key under user_id."""
        # Clean/normalize key
        resource_key = resource_key.strip()
        if user_id not in self._locks:
            self._locks[user_id] = {}
        if resource_key not in self._locks[user_id]:
            self._locks[user_id][resource_key] = asyncio.Lock()
        return self._locks[user_id][resource_key]

class MultiLockContext:
    """
    Context manager to acquire multiple locks in alphabetical order.
    Enforcing alphabetical order prevents circular wait deadlocks.
    """
    def __init__(self, registry: ResourceLockRegistry, user_id: str, resource_keys: List[str]):
        self.registry = registry
        self.user_id = user_id
        # Remove duplicates and sort alphabetically to prevent deadlocks
        self.keys = sorted(list(set(resource_keys)))
        self.locks: List[asyncio.Lock] = []

    async def __aenter__(self):
        for key in self.keys:
            lock = self.registry.get_lock(self.user_id, key)
            await lock.acquire()
            self.locks.append(lock)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Release in reverse order (optional but standard)
        for lock in reversed(self.locks):
            lock.release()


_lock_registry = ResourceLockRegistry()

def get_resource_lock_registry() -> ResourceLockRegistry:
    global _lock_registry
    return _lock_registry
