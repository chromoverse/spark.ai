"""
Speculative Cache — Per-session in-memory store for pre-fetched context.

During speech, we speculatively load user details, recent messages, and RAG
context so they are instantly available when the user stops speaking.

Thread-safe via asyncio.Lock.  Auto-evicts entries after TTL_SECONDS.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TTL_SECONDS: float = 30.0       # cache entries expire after 30 s
CLEANUP_INTERVAL: int = 15      # sweep every 15 s


@dataclass
class SessionContext:
    """Pre-fetched context for a single recording session."""

    user_details: Optional[Dict[str, Any]] = None
    recent_messages: Optional[List[Dict[str, Any]]] = None
    rag_context: Optional[List[Dict[str, Any]]] = None
    partial_transcript: str = ""
    rag_query_text: str = ""          # the transcript used for the latest RAG
    user_loaded: bool = False         # True once user + recent loaded
    rag_in_flight: bool = False       # True while RAG query is running
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.updated_at) > TTL_SECONDS

    def touch(self) -> None:
        self.updated_at = time.time()


class SpeculativeCache:
    """
    Session-scoped cache of speculatively pre-fetched context.

    Usage:
        cache = speculative_cache  # module-level singleton

        # During speech (from each transcribed chunk):
        ctx = cache.get_or_create(session_id)
        ctx.partial_transcript = "latest partial..."
        ctx.user_details = ...

        # When user stops speaking:
        ctx = cache.pop(session_id)
        if ctx and ctx.user_details:
            # skip loading — use pre-fetched data
    """

    def __init__(self) -> None:
        self._store: Dict[str, SessionContext] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None

    async def get_or_create(self, session_id: str) -> SessionContext:
        """Get existing context or create a new one."""
        async with self._lock:
            if session_id not in self._store:
                self._store[session_id] = SessionContext()
                logger.debug("🗄️ Speculative cache: new session %s…", session_id[:8])
            ctx = self._store[session_id]
            ctx.touch()
            return ctx

    async def get(self, session_id: str) -> Optional[SessionContext]:
        """Get context if it exists (does NOT create)."""
        async with self._lock:
            ctx = self._store.get(session_id)
            if ctx and not ctx.is_expired:
                ctx.touch()
                return ctx
            return None

    async def pop(self, session_id: str) -> Optional[SessionContext]:
        """Remove and return context for a session."""
        async with self._lock:
            ctx = self._store.pop(session_id, None)
            if ctx:
                logger.debug("🗄️ Speculative cache: popped session %s…", session_id[:8])
            return ctx

    async def cleanup(self, session_id: str) -> None:
        """Explicitly remove a session."""
        async with self._lock:
            self._store.pop(session_id, None)

    # ── Background Cleanup ─────────────────────────────────────────────────

    def start_cleanup_loop(self) -> None:
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info("🔄 Speculative cache cleanup loop started")

    async def _cleanup_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(CLEANUP_INTERVAL)
                await self._evict_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("❌ Speculative cache cleanup error: %s", e)

    async def _evict_expired(self) -> None:
        async with self._lock:
            expired = [
                sid for sid, ctx in self._store.items()
                if ctx.is_expired
            ]
            for sid in expired:
                del self._store[sid]
            if expired:
                logger.debug("🧹 Evicted %d stale speculative cache entries", len(expired))


# ── Module-level singleton ─────────────────────────────────────────────────
speculative_cache = SpeculativeCache()
