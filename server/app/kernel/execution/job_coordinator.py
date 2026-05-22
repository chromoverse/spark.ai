"""
Job Coordinator — Global registry of active jobs per user.

Tracks all active execution jobs, provides fuzzy cancellation,
enforces quotas, and garbage-collects finished jobs.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Settings ────────────────────────────────────────────────────────────────────

MAX_ACTIVE_JOBS_PER_USER = 5
JOB_GC_TTL_SECONDS = 600  # 10 minutes after termination


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    REPLANNING = "replanning"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class JobMetadata:
    job_id: str
    user_id: str
    goal: str                   # Original user query / intent description
    status: JobStatus = JobStatus.RUNNING
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None

    # Replan budget tracking
    replan_count: int = 0
    replan_tokens_used: int = 0

    # Per-task replan tracking: maps lineage_id -> replan count
    task_replan_counts: Dict[str, int] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}


@dataclass
class QueuedJob:
    """A job waiting in queue for an active slot."""
    job_id: str
    user_id: str
    goal: str
    created_at: float = field(default_factory=time.time)
    # Async callback that starts the job (registers tasks + starts engine).
    # Set by the caller (SQH / trigger_handler) after queueing.
    start_callback: Optional[Any] = None  # Callable[[], Coroutine]


class AmbiguousMatch(Exception):
    """Multiple jobs matched a fuzzy query."""
    def __init__(self, candidates: List[JobMetadata]):
        self.candidates = candidates
        goals = ", ".join(f'"{c.goal[:50]}"' for c in candidates)
        super().__init__(f"Multiple jobs matched: {goals}")


class JobQuotaExceeded(Exception):
    """User has too many active jobs."""
    pass


class JobNotFound(Exception):
    """No matching job found."""
    pass


class JobCoordinator:
    """
    Central registry for all active and recently-finished jobs.

    Responsibilities:
    - Register new jobs, enforce per-user quota
    - Track job lifecycle (running → replanning → completed/failed/cancelled)
    - Provide fuzzy matching for cancellation by intent
    - Garbage-collect terminated jobs after TTL
    """

    def __init__(self):
        # user_id -> { job_id -> JobMetadata }
        self._jobs: Dict[str, Dict[str, JobMetadata]] = {}
        # user_id -> [QueuedJob, ...] (FIFO order)
        self._queue: Dict[str, List[QueuedJob]] = {}
        self._gc_lock = asyncio.Lock()

    # ── Registration ────────────────────────────────────────────────────────

    def register_job(
        self, user_id: str, goal: str, job_id: Optional[str] = None,
    ) -> tuple[str, bool]:
        """
        Register a new job for the user.

        If all active slots are full the job is placed in a FIFO queue and will
        be automatically promoted when a slot frees up.

        Returns:
            (job_id, queued) — *queued* is True when the job was queued rather
            than immediately active.  The caller should set a start callback
            via :meth:`set_start_callback` so the coordinator can launch the
            job when a slot opens.
        """
        job_id = job_id or f"job_{uuid.uuid4().hex[:8]}"
        user_jobs = self._jobs.setdefault(user_id, {})

        # Count only genuinely running jobs (not QUEUED ones)
        running_count = sum(
            1 for j in user_jobs.values()
            if not j.is_terminal and j.status != JobStatus.QUEUED
        )

        if running_count >= MAX_ACTIVE_JOBS_PER_USER:
            # Queue instead of reject
            meta = JobMetadata(
                job_id=job_id, user_id=user_id, goal=goal,
                status=JobStatus.QUEUED,
            )
            user_jobs[job_id] = meta
            entry = QueuedJob(job_id=job_id, user_id=user_id, goal=goal)
            self._queue.setdefault(user_id, []).append(entry)
            logger.info(
                "[JobCoordinator] Queued job %s for user %s (slot full): %s",
                job_id, user_id, goal[:80],
            )
            return job_id, True

        meta = JobMetadata(job_id=job_id, user_id=user_id, goal=goal)
        user_jobs[job_id] = meta
        logger.info("[JobCoordinator] Registered job %s for user %s: %s", job_id, user_id, goal[:80])
        return job_id, False

    def set_start_callback(self, user_id: str, job_id: str, callback) -> None:
        """Attach the async start callback to a queued job."""
        queue = self._queue.get(user_id, [])
        for entry in queue:
            if entry.job_id == job_id:
                entry.start_callback = callback
                return
        logger.warning("[JobCoordinator] set_start_callback: job %s not found in queue", job_id)

    # ── Status transitions ──────────────────────────────────────────────────

    def update_status(self, user_id: str, job_id: str, status: JobStatus) -> None:
        meta = self._get(user_id, job_id)
        if not meta:
            return
        old = meta.status
        meta.status = status
        if status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            meta.finished_at = time.time()
            # A slot freed up — try to promote a queued job
            self._schedule_promotion(user_id)
        logger.info("[JobCoordinator] Job %s: %s -> %s", job_id, old.value, status.value)

    # ── Queue promotion ────────────────────────────────────────────────────

    def _schedule_promotion(self, user_id: str) -> None:
        """Schedule async promotion of the next queued job (fire-and-forget)."""
        if not self._queue.get(user_id):
            return
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._try_promote(user_id))
        except RuntimeError:
            pass  # No event loop (sync tests)

    async def _try_promote(self, user_id: str) -> None:
        """Promote the next queued job into an active slot."""
        queue = self._queue.get(user_id)
        if not queue:
            return

        user_jobs = self._jobs.get(user_id, {})
        running_count = sum(
            1 for j in user_jobs.values()
            if not j.is_terminal and j.status != JobStatus.QUEUED
        )
        if running_count >= MAX_ACTIVE_JOBS_PER_USER:
            return

        entry = queue.pop(0)
        if not queue:
            del self._queue[user_id]

        meta = user_jobs.get(entry.job_id)
        if meta:
            meta.status = JobStatus.RUNNING

        logger.info(
            "[JobCoordinator] Promoting queued job %s for user %s: %s",
            entry.job_id, user_id, entry.goal[:60],
        )

        # Notify UI
        try:
            from app.socket.utils import socket_emit
            await socket_emit("job:promoted", {
                "user_id": user_id,
                "job_id": entry.job_id,
                "goal": entry.goal[:200],
            }, user_id=user_id)
        except Exception:
            pass

        # Fire the start callback (registers tasks + starts engine)
        if entry.start_callback:
            try:
                await entry.start_callback()
            except Exception as exc:
                logger.error(
                    "[JobCoordinator] Promotion start failed for %s: %s",
                    entry.job_id, exc, exc_info=True,
                )
                if meta:
                    meta.status = JobStatus.FAILED
                    meta.finished_at = time.time()
        else:
            logger.warning("[JobCoordinator] Queued job %s has no start callback — marking failed", entry.job_id)
            if meta:
                meta.status = JobStatus.FAILED
                meta.finished_at = time.time()

    def increment_replan(self, user_id: str, job_id: str, tokens_used: int = 0) -> int:
        """Increment replan count and return the new count."""
        meta = self._get(user_id, job_id)
        if not meta:
            return 0
        meta.replan_count += 1
        meta.replan_tokens_used += tokens_used
        return meta.replan_count

    def increment_task_replan(self, user_id: str, job_id: str, lineage_id: str) -> int:
        """Increment per-task replan count, return new count."""
        meta = self._get(user_id, job_id)
        if not meta:
            return 0
        meta.task_replan_counts[lineage_id] = meta.task_replan_counts.get(lineage_id, 0) + 1
        return meta.task_replan_counts[lineage_id]

    # ── Queries ─────────────────────────────────────────────────────────────

    def get_job(self, user_id: str, job_id: str) -> Optional[JobMetadata]:
        return self._get(user_id, job_id)

    def get_active_jobs(self, user_id: str) -> List[JobMetadata]:
        user_jobs = self._jobs.get(user_id, {})
        return [j for j in user_jobs.values() if not j.is_terminal]

    def get_all_jobs(self, user_id: str) -> List[JobMetadata]:
        return list(self._jobs.get(user_id, {}).values())

    def get_queued_jobs(self, user_id: str) -> List[QueuedJob]:
        return list(self._queue.get(user_id, []))

    def cancel_queued_job(self, user_id: str, job_id: str) -> bool:
        """Remove a queued job. Returns True if found and cancelled."""
        queue = self._queue.get(user_id, [])
        for i, entry in enumerate(queue):
            if entry.job_id == job_id:
                queue.pop(i)
                if not queue:
                    self._queue.pop(user_id, None)
                meta = self._get(user_id, job_id)
                if meta:
                    meta.status = JobStatus.CANCELLED
                    meta.finished_at = time.time()
                logger.info("[JobCoordinator] Cancelled queued job %s", job_id)
                return True
        return False

    # ── Fuzzy cancellation ──────────────────────────────────────────────────

    def resolve_job_by_query(self, user_id: str, query: str) -> str:
        """
        Resolve a natural-language reference to a job_id.

        Returns:
            job_id of the single matching job.
        Raises:
            JobNotFound: if no active jobs match.
            AmbiguousMatch: if multiple active jobs match — caller should disambiguate.
        """
        active = self.get_active_jobs(user_id)
        if not active:
            raise JobNotFound("No active jobs to cancel.")

        query_lower = query.lower()
        scored: List[tuple[int, JobMetadata]] = []
        for job in active:
            goal_lower = job.goal.lower()
            # Simple word-overlap scoring
            query_words = set(query_lower.split())
            goal_words = set(goal_lower.split())
            overlap = len(query_words & goal_words)
            if overlap > 0:
                scored.append((overlap, job))

        if not scored:
            # Fallback: if only one active job, just match it
            if len(active) == 1:
                return active[0].job_id
            raise JobNotFound(f"No active jobs match '{query}'.")

        scored.sort(key=lambda x: x[0], reverse=True)
        top_score = scored[0][0]
        top_matches = [j for s, j in scored if s == top_score]

        if len(top_matches) > 1:
            raise AmbiguousMatch(top_matches)

        return top_matches[0].job_id

    # ── Garbage collection ──────────────────────────────────────────────────

    async def gc(self) -> int:
        """Remove terminated jobs older than JOB_GC_TTL_SECONDS. Returns count removed."""
        async with self._gc_lock:
            now = time.time()
            removed = 0
            for user_id in list(self._jobs.keys()):
                user_jobs = self._jobs[user_id]
                to_remove = [
                    jid for jid, meta in user_jobs.items()
                    if meta.is_terminal and meta.finished_at and (now - meta.finished_at) > JOB_GC_TTL_SECONDS
                ]
                for jid in to_remove:
                    del user_jobs[jid]
                    removed += 1
                if not user_jobs:
                    del self._jobs[user_id]

                # Clean up stale queue entries whose metadata was already GC'd
                queue = self._queue.get(user_id, [])
                self._queue[user_id] = [
                    e for e in queue if e.job_id in self._jobs.get(user_id, {})
                ]
                if not self._queue.get(user_id):
                    self._queue.pop(user_id, None)

            if removed:
                logger.info("[JobCoordinator] GC removed %d terminated jobs", removed)
            return removed

    # ── Internal ────────────────────────────────────────────────────────────

    def _get(self, user_id: str, job_id: str) -> Optional[JobMetadata]:
        return self._jobs.get(user_id, {}).get(job_id)


# ── Singleton ───────────────────────────────────────────────────────────────────

_coordinator: Optional[JobCoordinator] = None


def get_job_coordinator() -> JobCoordinator:
    global _coordinator
    if _coordinator is None:
        _coordinator = JobCoordinator()
    return _coordinator
