"""In-memory TTL cache for idempotent tool results."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Tools safe to cache (read-only / idempotent)
CACHEABLE_TOOLS = frozenset({
    "weather_current", "weather_forecast", "weather",
    "system_info", "battery_status", "network_status",
    "web_search", "artifact_list", "system_query",
    "current_location", "tool_catalog", "agent_status",
})


class ToolResultCache:
    def __init__(self, default_ttl: int = 30):
        self._cache: Dict[str, tuple[float, Any]] = {}
        self.default_ttl = default_ttl

    def _make_key(self, tool_name: str, inputs: dict) -> str:
        # Strip internal keys before hashing
        clean = {k: v for k, v in inputs.items() if not k.startswith("_")}
        raw = json.dumps(clean, sort_keys=True, default=str)
        return f"{tool_name}:{hashlib.md5(raw.encode()).hexdigest()}"

    def get(self, tool_name: str, inputs: dict) -> Optional[Any]:
        if tool_name not in CACHEABLE_TOOLS:
            return None
        key = self._make_key(tool_name, inputs)
        entry = self._cache.get(key)
        if entry and (time.time() - entry[0]) < self.default_ttl:
            logger.info("Cache HIT for %s", tool_name)
            return entry[1]
        if entry:
            del self._cache[key]
        return None

    def put(self, tool_name: str, inputs: dict, output: Any) -> None:
        if tool_name not in CACHEABLE_TOOLS:
            return
        key = self._make_key(tool_name, inputs)
        self._cache[key] = (time.time(), output)


_instance: Optional[ToolResultCache] = None


def get_tool_result_cache() -> ToolResultCache:
    global _instance
    if _instance is None:
        _instance = ToolResultCache()
    return _instance
