"""Base pattern for service clients with caching."""
import time
import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class ClientCache:
    """Simple TTL cache for authenticated service clients."""

    def __init__(self, ttl_seconds: int = 3000):
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._ttl = ttl_seconds

    def get(self, key: str) -> Optional[Any]:
        if key in self._cache:
            cached_time, client = self._cache[key]
            if time.time() - cached_time < self._ttl:
                return client
            del self._cache[key]
        return None

    def set(self, key: str, client: Any) -> None:
        self._cache[key] = (time.time(), client)

    def invalidate(self, key: str) -> None:
        self._cache.pop(key, None)
