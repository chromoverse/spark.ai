from __future__ import annotations

from typing import Any, Dict, Optional

from app.agent.runtime.code_context_service import get_code_context_service
from app.kernel.persistence.services import get_kernel_log_service, get_kernel_stats_service


class SmartContextService:
    """Read-only smart context adapter for Section 2 (agent runtime)."""

    async def get_user_task_history(
        self,
        user_id: str,
        window: str = "90d",
        limit: int = 50,
        cursor: int = 0,
    ) -> Dict[str, Any]:
        return await get_kernel_stats_service().get_user_task_history(
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
        return await get_kernel_stats_service().get_user_tool_metrics(
            user_id=user_id,
            window=window,
            limit=limit,
            sort=sort,
        )

    async def get_user_metrics(
        self,
        user_id: str,
        window: str = "30d",
    ) -> Dict[str, Any]:
        return await get_kernel_stats_service().get_user_metrics(user_id=user_id, window=window)

    async def get_runtime_tool_summary(self) -> Dict[str, Any]:
        return await get_kernel_stats_service().get_runtime_summary()

    async def get_user_log_window(
        self,
        user_id: str,
        level: Optional[str] = None,
        cursor: int = 0,
        limit: int = 100,
        max_lines: int = 50,
        max_bytes: int = 12_000,
    ) -> Dict[str, Any]:
        """
        User-scoped capped log window with trimming for LLM context safety.
        """
        result = await get_kernel_log_service().query_user_logs(
            user_id=user_id,
            level=level,
            cursor=cursor,
            limit=limit,
        )

        lines = result.get("logs", [])
        trimmed = bool(result.get("trimmed", False))

        capped: list[dict[str, Any]] = []
        size = 0
        for item in lines[:max_lines]:
            encoded_size = len(str(item).encode("utf-8"))
            if size + encoded_size > max_bytes:
                trimmed = True
                break
            capped.append(item)
            size += encoded_size

        if len(capped) < len(lines):
            trimmed = True

        return {
            **result,
            "logs": capped,
            "trimmed": trimmed,
            "trimming_summary": self._build_trim_summary(capped, trimmed),
        }

    async def get_repo_context(
        self,
        query: str,
        limit: int = 5,
        max_bytes: int = 10_000,
    ) -> Dict[str, Any]:
        return get_code_context_service().repo_search(
            query=query,
            limit=max(1, min(limit, 20)),
            max_bytes=max(1_000, min(max_bytes, 40_000)),
        )

    async def repo_read_snippet(
        self,
        file_path: str,
        start_line: int = 1,
        line_count: int = 80,
        max_bytes: int = 10_000,
    ) -> Dict[str, Any]:
        return get_code_context_service().repo_read_snippet(
            file_path=file_path,
            start_line=start_line,
            line_count=line_count,
            max_bytes=max_bytes,
        )

    @staticmethod
    def _build_trim_summary(logs: list[dict[str, Any]], trimmed: bool) -> str:
        if not logs:
            return "No matching user-scoped logs found."

        last = logs[-1]
        base = (
            f"Returned {len(logs)} user-scoped log entries; "
            f"last event='{last.get('message', '')}' at {last.get('timestamp', '')}."
        )
        if trimmed:
            return base + " Additional lines were trimmed to keep context size bounded."
        return base


_smart_context_service: SmartContextService | None = None


def get_smart_context_service() -> SmartContextService:
    global _smart_context_service
    if _smart_context_service is None:
        _smart_context_service = SmartContextService()
    return _smart_context_service


