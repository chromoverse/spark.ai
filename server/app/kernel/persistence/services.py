from __future__ import annotations

from typing import Any, Dict

from app.kernel.observability.log_index import get_kernel_log_index
from app.kernel.persistence.persistence_router import get_kernel_persistence_router
from app.kernel.persistence.stats_store import get_kernel_stats_store


class KernelStatsService:
    async def get_user_metrics(self, user_id: str, window: str = "30d") -> Dict[str, Any]:
        return await get_kernel_stats_store().get_user_metrics(user_id=user_id, window=window)

    async def get_user_task_history(
        self,
        user_id: str,
        window: str = "90d",
        limit: int = 50,
        cursor: int = 0,
    ) -> Dict[str, Any]:
        return await get_kernel_stats_store().get_user_task_history(
            user_id=user_id,
            window=window,
            limit=limit,
            cursor=cursor,
        )

    async def get_user_tool_metrics(
        self,
        user_id: str,
        window: str = "30d",
        limit: int = 10,
        sort: str = "score",
    ) -> Dict[str, Any]:
        return await get_kernel_stats_store().get_user_tool_metrics(
            user_id=user_id,
            window=window,
            limit=limit,
            sort=sort,
        )

    async def get_runtime_summary(self) -> Dict[str, Any]:
        summary = await get_kernel_stats_store().get_runtime_summary()
        summary["cached_users"] = get_kernel_persistence_router().cached_user_count()
        return summary


class KernelLogService:
    async def query_user_logs(
        self,
        user_id: str,
        level: str | None = None,
        startup_id: str | None = None,
        cursor: int = 0,
        limit: int = 100,
    ) -> Dict[str, Any]:
        current_startup = get_kernel_log_index().startup_id
        if startup_id and startup_id != current_startup:
            return {
                "logs": [],
                "next_cursor": cursor,
                "trimmed": False,
                "startup_id": current_startup,
                "message": "Requested startup_id is not active in current process.",
            }

        result = await get_kernel_log_index().query_user_logs(
            user_id=user_id,
            level=level,
            cursor=cursor,
            limit=limit,
        )
        return {
            "logs": result.logs,
            "next_cursor": result.next_cursor,
            "trimmed": result.trimmed,
            "startup_id": result.startup_id,
        }


_stats_service: KernelStatsService | None = None
_log_service: KernelLogService | None = None


def get_kernel_stats_service() -> KernelStatsService:
    global _stats_service
    if _stats_service is None:
        _stats_service = KernelStatsService()
    return _stats_service


def get_kernel_log_service() -> KernelLogService:
    global _log_service
    if _log_service is None:
        _log_service = KernelLogService()
    return _log_service


