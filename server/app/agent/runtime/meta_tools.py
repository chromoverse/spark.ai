from __future__ import annotations

from typing import Any, Dict

from app.agent.runtime.capability_service import get_capability_service
from app.agent.runtime.smart_context_service import get_smart_context_service
from app.kernel import KernelEvent, emit_kernel_event
from app.kernel.persistence.services import get_kernel_stats_service


async def kernel_history_lookup(user_id: str, window: str = "90d", limit: int = 10) -> Dict[str, Any]:
    await _emit_meta_tool_event(
        user_id=user_id,
        meta_tool="get_user_task_history",
        payload={"window": window, "limit": limit},
    )
    return await get_smart_context_service().get_user_task_history(
        user_id=user_id,
        window=window,
        limit=limit,
    )


async def kernel_success_rate_lookup(user_id: str, window: str = "30d") -> Dict[str, Any]:
    await _emit_meta_tool_event(
        user_id=user_id,
        meta_tool="get_user_metrics",
        payload={"window": window},
    )
    return await get_smart_context_service().get_user_metrics(user_id=user_id, window=window)


async def kernel_tool_inventory_lookup(user_id: str = "system") -> Dict[str, Any]:
    await _emit_meta_tool_event(
        user_id=user_id,
        meta_tool="get_runtime_tool_summary",
        payload={},
    )
    return await get_kernel_stats_service().get_runtime_summary()


async def kernel_best_tools_lookup(
    user_id: str,
    window: str = "30d",
    limit: int = 5,
) -> Dict[str, Any]:
    await _emit_meta_tool_event(
        user_id=user_id,
        meta_tool="get_user_tool_metrics",
        payload={"window": window, "limit": limit},
    )
    return await get_smart_context_service().get_user_tool_metrics(
        user_id=user_id,
        window=window,
        limit=limit,
        sort="score",
    )


async def kernel_log_lookup(
    user_id: str,
    level: str | None = None,
    limit: int = 50,
    max_lines: int = 20,
    max_bytes: int = 8_000,
) -> Dict[str, Any]:
    await _emit_meta_tool_event(
        user_id=user_id,
        meta_tool="get_user_log_window",
        payload={"level": level, "limit": limit},
    )
    return await get_smart_context_service().get_user_log_window(
        user_id=user_id,
        level=level,
        limit=limit,
        max_lines=max_lines,
        max_bytes=max_bytes,
    )


async def repo_search_lookup(
    user_id: str,
    query: str,
    limit: int = 5,
    max_bytes: int = 10_000,
) -> Dict[str, Any]:
    await _emit_meta_tool_event(
        user_id=user_id,
        meta_tool="repo_search",
        payload={"query": query, "limit": limit},
    )
    return await get_smart_context_service().get_repo_context(
        query=query,
        limit=limit,
        max_bytes=max_bytes,
    )


async def repo_read_snippet_lookup(
    user_id: str,
    file_path: str,
    start_line: int = 1,
    line_count: int = 80,
    max_bytes: int = 10_000,
) -> Dict[str, Any]:
    await _emit_meta_tool_event(
        user_id=user_id,
        meta_tool="repo_read_snippet",
        payload={
            "file_path": file_path,
            "start_line": start_line,
            "line_count": line_count,
        },
    )
    return await get_smart_context_service().repo_read_snippet(
        file_path=file_path,
        start_line=start_line,
        line_count=line_count,
        max_bytes=max_bytes,
    )


async def capability_snapshot_lookup(user_id: str) -> Dict[str, Any]:
    await _emit_meta_tool_event(
        user_id=user_id,
        meta_tool="get_capability_snapshot",
        payload={},
    )
    return await get_capability_service().get_capability_snapshot(user_id=user_id)


async def _emit_meta_tool_event(user_id: str, meta_tool: str, payload: Dict[str, Any]) -> None:
    await emit_kernel_event(
        KernelEvent(
            event_type="agent_meta_tool_invoked",
            user_id=user_id,
            status="success",
            payload={
                "meta_tool": meta_tool,
                **payload,
            },
        )
    )


