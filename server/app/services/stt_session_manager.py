"""
STT Session Manager — In-memory store for streaming speech-to-text chunks.

Each recording session is identified by a unique session_id.  Audio chunks
arrive continuously (every ~2 s), are transcribed individually, and stored
here keyed by (session_id, sequence_number).  When the user stops speaking
the full text is assembled in sequence order and returned.

Thread-safe via asyncio.Lock (single writer per session).
Stale sessions are auto-evicted after TTL_SECONDS.
Pending-transcription tracking prevents the race where user-stop-speaking
arrives before in-flight chunk transcriptions finish.
"""

import asyncio
import logging
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────
TTL_SECONDS: int = 300  # 5 minutes — safety net for abandoned sessions
CLEANUP_INTERVAL: int = 60  # Run cleanup sweep every 60 s
PENDING_WAIT_TIMEOUT: float = 30.0  # Max seconds to wait for in-flight chunks


class _SessionData:
    """Internal container for one recording session."""

    __slots__ = ("chunks", "created_at", "updated_at", "pending_count", "all_done")

    def __init__(self) -> None:
        self.chunks: Dict[int, str] = {}  # seq → transcribed text
        self.created_at: float = time.time()
        self.updated_at: float = self.created_at
        self.pending_count: int = 0  # in-flight transcriptions
        self.all_done: asyncio.Event = asyncio.Event()
        self.all_done.set()  # starts with nothing pending

    def add_chunk(self, seq: int, text: str) -> None:
        self.chunks[seq] = text
        self.updated_at = time.time()

    def increment_pending(self) -> None:
        """Call BEFORE starting a transcription task."""
        self.pending_count += 1
        self.all_done.clear()

    def decrement_pending(self) -> None:
        """Call AFTER a transcription task completes (success or failure)."""
        self.pending_count = max(0, self.pending_count - 1)
        if self.pending_count == 0:
            self.all_done.set()

    def get_full_text(self) -> str:
        """Concatenate all chunks in sequence order."""
        if not self.chunks:
            return ""
        ordered = sorted(self.chunks.items(), key=lambda kv: kv[0])
        return " ".join(text for _, text in ordered if text.strip()).strip()

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.updated_at) > TTL_SECONDS


class STTSessionManager:
    """
    Singleton manager for streaming STT sessions.

    Usage:
        manager = stt_session_manager  # module-level singleton

        # Before transcribing each chunk:
        manager.increment_pending(session_id)
        try:
            text = await transcribe(...)
            manager.add_chunk(session_id, seq, text)
        finally:
            manager.decrement_pending(session_id)

        # When user stops speaking:
        await manager.wait_for_pending(session_id)
        full_text = manager.get_full_text(session_id)
        manager.cleanup(session_id)
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, _SessionData] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None

    # ── helpers ────────────────────────────────────────────────────────────

    def _get_or_create(self, session_id: str) -> _SessionData:
        """Get or create session (must be called under lock)."""
        if session_id not in self._sessions:
            self._sessions[session_id] = _SessionData()
            logger.info(f"📝 New STT session: {session_id[:8]}…")
        return self._sessions[session_id]

    # ── Public API ─────────────────────────────────────────────────────────

    async def increment_pending(self, session_id: str) -> None:
        """Mark that a transcription task is about to start."""
        async with self._lock:
            session = self._get_or_create(session_id)
            session.increment_pending()

    async def decrement_pending(self, session_id: str) -> None:
        """Mark that a transcription task finished."""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.decrement_pending()

    async def add_chunk(self, session_id: str, seq: int, text: str) -> None:
        """Store a transcribed chunk for the given session + sequence."""
        async with self._lock:
            session = self._get_or_create(session_id)
            session.add_chunk(seq, text)
            logger.debug(
                f"📝 Session {session_id[:8]}… chunk #{seq} stored "
                f"({session.chunk_count} total)"
            )

    async def wait_for_pending(self, session_id: str) -> bool:
        """
        Wait until all in-flight transcriptions for a session are done.
        Returns True if all finished, False on timeout.
        """
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session or session.pending_count == 0:
                return True
            event = session.all_done
            pending = session.pending_count

        logger.info(
            f"⏳ Waiting for {pending} pending transcription(s) "
            f"on session {session_id[:8]}…"
        )

        try:
            await asyncio.wait_for(event.wait(), timeout=PENDING_WAIT_TIMEOUT)
            logger.info(f"✅ All transcriptions done for session {session_id[:8]}…")
            return True
        except asyncio.TimeoutError:
            logger.warning(
                f"⏰ Timed out waiting for pending transcriptions "
                f"on session {session_id[:8]}…"
            )
            return False

    async def get_full_text(self, session_id: str) -> str:
        """Return the full concatenated transcription for a session."""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                logger.warning(f"⚠️ Session not found: {session_id[:8]}…")
                return ""
            text = session.get_full_text()
            logger.info(
                f"📝 Session {session_id[:8]}… assembled "
                f"({session.chunk_count} chunks): '{text[:120]}'"
            )
            return text

    async def cleanup(self, session_id: str) -> None:
        """Remove a session from memory."""
        async with self._lock:
            removed = self._sessions.pop(session_id, None)
            if removed:
                logger.info(
                    f"🧹 Session {session_id[:8]}… cleaned up "
                    f"({removed.chunk_count} chunks)"
                )

    async def get_chunk_count(self, session_id: str) -> int:
        """Get the number of chunks stored for a session."""
        async with self._lock:
            session = self._sessions.get(session_id)
            return session.chunk_count if session else 0

    async def get_current_partial_text(self, session_id: str) -> str:
        """
        Return the current partial transcript WITHOUT waiting for pending chunks.
        Used by speculative pre-fetch to build RAG queries from in-progress speech.
        """
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return ""
            return session.get_full_text()

    async def get_last_chunk_text(self, session_id: str) -> str:
        """Return the text of the most recent chunk for context continuity."""
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session or not session.chunks:
                return ""
            max_seq = max(session.chunks.keys())
            return session.chunks[max_seq]

    @property
    def active_session_count(self) -> int:
        return len(self._sessions)

    # ── Background Cleanup ─────────────────────────────────────────────────

    def start_cleanup_loop(self) -> None:
        """Start the background TTL eviction loop (call once at startup)."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info("🔄 STT session cleanup loop started")

    async def _cleanup_loop(self) -> None:
        """Periodically evict expired sessions."""
        while True:
            try:
                await asyncio.sleep(CLEANUP_INTERVAL)
                await self._evict_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Cleanup loop error: {e}", exc_info=True)

    async def _evict_expired(self) -> None:
        async with self._lock:
            expired = [
                sid
                for sid, data in self._sessions.items()
                if data.is_expired
            ]
            for sid in expired:
                removed = self._sessions.pop(sid)
                logger.info(
                    f"🧹 Evicted stale session {sid[:8]}… "
                    f"({removed.chunk_count} chunks, "
                    f"idle {time.time() - removed.updated_at:.0f}s)"
                )
            if expired:
                logger.info(f"🧹 Evicted {len(expired)} stale session(s)")


# ── Module-level singleton ─────────────────────────────────────────────────
stt_session_manager = STTSessionManager()
