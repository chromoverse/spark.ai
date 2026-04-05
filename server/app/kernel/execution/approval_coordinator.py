from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)

ApprovalCallback = Callable[[str, str, bool], Awaitable[None]]


@dataclass(slots=True)
class PendingApproval:
    user_id: str
    request_id: str
    execution_id: str
    question: str
    callback: ApprovalCallback
    created_at: datetime


class ApprovalCoordinator:
    """Central approval and sidecar-task registry for async resume flows."""

    def __init__(self) -> None:
        self._pending: Dict[tuple[str, str], PendingApproval] = {}
        self._background_tasks: Dict[tuple[str, str], set[asyncio.Task[None]]] = {}

    def register_request(
        self,
        *,
        user_id: str,
        request_id: str,
        execution_id: str,
        question: str,
        callback: ApprovalCallback,
    ) -> bool:
        key = (user_id, request_id)
        if key in self._pending:
            logger.warning("⚠️ Duplicate approval request ignored for %s/%s", user_id, request_id)
            return False
        self._pending[key] = PendingApproval(
            user_id=user_id,
            request_id=request_id,
            execution_id=execution_id,
            question=question,
            callback=callback,
            created_at=datetime.now(),
        )
        return True

    async def resolve_request(self, user_id: str, request_id: str, approved: bool) -> bool:
        key = (user_id, request_id)
        pending = self._pending.pop(key, None)
        if pending is None:
            logger.warning("⚠️ Approval response with no pending request: %s/%s", user_id, request_id)
            return False
        try:
            await pending.callback(user_id, request_id, approved)
            return True
        except Exception as exc:
            logger.error("Failed to resolve approval callback for %s/%s: %s", user_id, request_id, exc, exc_info=True)
            return False

    def cancel_request(self, user_id: str, request_id: str) -> bool:
        return self._pending.pop((user_id, request_id), None) is not None

    def cancel_user_requests(self, user_id: str, execution_id: Optional[str] = None) -> int:
        """Drop pending approvals and cancel tracked sidecar tasks for a user/execution."""
        removed = 0
        for key, pending in list(self._pending.items()):
            if pending.user_id != user_id:
                continue
            if execution_id and pending.execution_id != execution_id:
                continue
            self._pending.pop(key, None)
            removed += 1

        task_keys = [
            key
            for key in list(self._background_tasks.keys())
            if key[0] == user_id and (execution_id is None or key[1] == execution_id)
        ]
        for key in task_keys:
            tasks = self._background_tasks.pop(key, set())
            for task in list(tasks):
                task.cancel()
                removed += 1

        return removed

    def track_background_task(self, user_id: str, execution_id: str, task: asyncio.Task[None]) -> None:
        key = (user_id, execution_id)
        bucket = self._background_tasks.setdefault(key, set())
        bucket.add(task)

        def _cleanup(done_task: asyncio.Task[None]) -> None:
            bucket.discard(done_task)
            if not bucket:
                self._background_tasks.pop(key, None)

        task.add_done_callback(_cleanup)


_approval_coordinator: Optional[ApprovalCoordinator] = None


def get_approval_coordinator() -> ApprovalCoordinator:
    global _approval_coordinator
    if _approval_coordinator is None:
        _approval_coordinator = ApprovalCoordinator()
    return _approval_coordinator


def init_approval_coordinator() -> ApprovalCoordinator:
    global _approval_coordinator
    _approval_coordinator = ApprovalCoordinator()
    return _approval_coordinator
