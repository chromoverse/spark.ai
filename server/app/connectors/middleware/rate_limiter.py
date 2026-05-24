"""Per-service per-user sliding window rate limiter."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Dict, Deque

# Default: 30 requests per 60 seconds per service per user
DEFAULT_WINDOW_S = 60
DEFAULT_MAX_REQUESTS = 30


class RateLimiter:
    def __init__(self, window_s: int = DEFAULT_WINDOW_S, max_requests: int = DEFAULT_MAX_REQUESTS):
        self.window_s = window_s
        self.max_requests = max_requests
        self._requests: Dict[str, Deque[float]] = defaultdict(deque)

    def allow(self, service: str, user_id: str) -> bool:
        """Return True if the request is allowed, False if rate limited."""
        key = f"{service}:{user_id}"
        now = time.time()
        window = self._requests[key]

        # Evict expired entries
        while window and window[0] < now - self.window_s:
            window.popleft()

        if len(window) >= self.max_requests:
            return False

        window.append(now)
        return True
