from __future__ import annotations

import re
import time
from typing import Optional

from app.models.pqh_response_model import CognitiveState, PQHResponse
from app.plugins.tools.catalog_service import get_tool_catalog_service


# ── Job-related indicators (cancel, status, active queries) ──────────────────
_JOB_QUERY_INDICATORS = (
    "cancel the job", "cancel that", "cancel it",
    "stop the job", "stop that", "stop everything", "stop all",
    "abort", "kill the job", "kill that",
    "what are you doing", "what's running", "what is running",
    "active job", "job status", "current task",
    "what happened to",
)


def is_meta_query(query: str) -> bool:
    text = query.lower()
    indicators = (
        "what task",
        "tasks did",
        "history",
        "success rate",
        "best tools",
        "tool params",
        "tool parameter",
        "tool arguments",
        "explain tool",
        "what is app_",
        "codebase",
        "source code",
        "server code",
        "which file",
        "logs",
        "error trace",
    )
    if any(token in text for token in indicators):
        return True
    if any(token in text for token in _JOB_QUERY_INDICATORS):
        return True
    return False


async def try_handle_meta_query(query: str, user_id: str) -> Optional[PQHResponse]:
    text = query.lower()
    catalog = get_tool_catalog_service()

    # ── Cancel / stop intent ───────────────────────────────────────────────
    if any(tok in text for tok in (
        "cancel the job", "cancel that", "cancel it",
        "stop the job", "stop that", "stop everything", "stop all",
        "abort", "kill the job", "kill that",
    )):
        result = await _handle_cancel(query, user_id)
        if result:
            return result
        # No active jobs matched — fall through to normal PQH

    # ── Active-job status queries ──────────────────────────────────────────
    if any(tok in text for tok in (
        "what are you doing", "what's running", "what is running",
        "active job", "job status", "current task",
        "what happened to",
    )):
        result = await _handle_job_status(query, user_id)
        if result:
            return result

    if "success rate" in text:
        from app.agent.runtime.meta_tools import kernel_success_rate_lookup

        data = await kernel_success_rate_lookup(user_id=user_id)
        answer = (
            f"In the last {data['window_days']} days: total tasks={data['total_tasks']}, "
            f"completed={data['completed']}, failed={data['failed']}, "
            f"success rate={data['success_rate']}%."
        )
        return _response(query, answer)

    if (
        "tool params" in text
        or "tool parameter" in text
        or "tool arguments" in text
    ):
        requested_tool = _extract_tool_name(query)
        if requested_tool:
            payload = catalog.params(requested_tool, include_examples=True)
        if payload:
            required = [
                name for name, spec in payload.get("params_schema", {}).items()
                if isinstance(spec, dict) and spec.get("required")
            ]
            answer = (
                f"{requested_tool} parameters: {', '.join(payload.get('params_schema', {}).keys()) or 'none'}. "
                f"Required: {', '.join(required) or 'none'}."
            )
            return _response(query, answer)

    if any(token in text for token in ("explain", "what is", "describe")):
        requested_tool = _extract_tool_name(query)
        if requested_tool:
            payload = catalog.detail(requested_tool, include_examples=True)
            if payload:
                semantic_tags = payload.get("semantic_tags", [])
                answer = (
                    f"{requested_tool}: {payload.get('description', '')} "
                    f"Execution target: {payload.get('execution_target', 'unknown')}. "
                    f"Tags: {', '.join(semantic_tags) or 'none'}."
                )
                return _response(query, answer)

    if "best tools" in text:
        from app.agent.runtime.meta_tools import kernel_best_tools_lookup

        data = await kernel_best_tools_lookup(user_id=user_id, limit=5)
        items = data.get("items", [])
        if not items:
            return _response(query, "No tool usage data available yet for this user.")
        labels = [f"{item['tool_name']} ({item['weighted_score']})" for item in items]
        return _response(query, "Top tools by weighted score: " + ", ".join(labels))

    if "log" in text or "error trace" in text:
        from app.agent.runtime.meta_tools import kernel_log_lookup

        logs = await kernel_log_lookup(
            user_id=user_id,
            level=None,
            limit=50,
            max_lines=20,
            max_bytes=8000,
        )
        summary = logs.get("trimming_summary", "No logs available.")
        return _response(query, summary)

    snippet = _extract_file_snippet_request(query)
    if snippet:
        try:
            from app.agent.runtime.meta_tools import repo_read_snippet_lookup

            data = await repo_read_snippet_lookup(
                user_id=user_id,
                file_path=snippet,
                start_line=1,
                line_count=80,
                max_bytes=8000,
            )
            answer = (
                f"Snippet from {data['path']} lines {data['start_line']}-{data['end_line']}:\n"
                f"{data['snippet'][:1400]}"
            )
            return _response(query, answer)
        except Exception as exc:
            return _response(query, f"Could not read requested file snippet: {exc}")

    if any(token in text for token in ("codebase", "source code", "server code", "where is", "which file")):
        from app.agent.runtime.meta_tools import repo_search_lookup

        search_query = _normalize_code_search_query(query)
        data = await repo_search_lookup(user_id=user_id, query=search_query, limit=5, max_bytes=8000)
        items = data.get("items", [])
        if not items:
            return _response(query, data.get("summary", "No matching code context found."))
        formatted = [f"{item['path']}:{item['line']} -> {item['snippet']}" for item in items[:3]]
        answer = data.get("summary", "Code matches found.") + " Top matches: " + " | ".join(formatted)
        return _response(query, answer)

    if "task" in text or "history" in text:
        from app.agent.runtime.meta_tools import kernel_history_lookup

        data = await kernel_history_lookup(user_id=user_id, window="90d", limit=5)
        items = data.get("items", [])
        if not items:
            return _response(query, "No task history found yet for this user.")

        fragments = []
        for item in items[:5]:
            fragments.append(
                f"{item.get('task_id', 'unknown')}:{item.get('status', 'unknown')}"
            )
        answer = "Recent tasks: " + ", ".join(fragments)
        return _response(query, answer)

    return None


# ── Job-management handlers ───────────────────────────────────────────────────

async def _handle_cancel(query: str, user_id: str) -> Optional[PQHResponse]:
    """Try to cancel a matching job.  Returns None when no match (lets PQH handle it)."""
    from app.kernel.execution.job_coordinator import (
        get_job_coordinator, AmbiguousMatch, JobNotFound,
    )
    from app.kernel.execution.execution_engine import get_execution_engine

    coordinator = get_job_coordinator()
    active = coordinator.get_active_jobs(user_id)
    if not active:
        return None  # No active jobs — not a job-cancel intent

    text = query.lower()

    # "stop all" / "stop everything" / "cancel all" → nuke everything
    if "stop all" in text or "stop everything" in text or "cancel all" in text:
        await get_execution_engine().stop_execution(user_id)
        return _response(query, f"Stopped all {len(active)} active job(s).")

    try:
        job_id = coordinator.resolve_job_by_query(user_id, query)
    except JobNotFound:
        return None
    except AmbiguousMatch as exc:
        names = ", ".join(f'"{c.goal[:50]}"' for c in exc.candidates)
        return _response(query, f"Multiple jobs match. Which one? {names}")

    try:
        await get_execution_engine().stop_execution(user_id, job_id=job_id)
        job = coordinator.get_job(user_id, job_id)
        goal = job.goal[:80] if job else "the job"
        return _response(query, f"Cancelled: {goal}")
    except Exception as exc:
        return _response(query, f"Couldn't cancel: {exc}")


async def _handle_job_status(query: str, user_id: str) -> Optional[PQHResponse]:
    """Summarise active and recently-finished jobs."""
    from app.kernel.execution.job_coordinator import get_job_coordinator

    coordinator = get_job_coordinator()
    active = coordinator.get_active_jobs(user_id)

    # Also surface recently finished jobs (last 2 min) for "what happened" queries
    all_jobs = coordinator.get_all_jobs(user_id)
    now = time.time()
    recent = [
        j for j in all_jobs
        if j.is_terminal and j.finished_at and (now - j.finished_at) < 120
    ]

    if not active and not recent:
        return _response(query, "Nothing running right now. I'm free.")

    lines: list[str] = []
    if active:
        for j in active:
            elapsed = int(now - j.created_at)
            lines.append(f"{j.goal[:60]} — {j.status.value}, {elapsed}s")
    if recent:
        for j in recent:
            ago = int(now - (j.finished_at or now))
            lines.append(f"{j.goal[:60]} — {j.status.value}, finished {ago}s ago")

    header = f"{len(active)} active, {len(recent)} recently finished" if recent else f"{len(active)} active job(s)"
    return _response(query, f"{header}:\n" + "\n".join(lines))


def _response(query: str, answer: str) -> PQHResponse:
    return PQHResponse(
        request_id="meta_query",
        cognitive_state=CognitiveState(
            user_query=query,
            emotion="neutral",
            thought_process="Answered using kernel runtime data.",
            answer=answer,
            answer_english=answer,
        ),
        requested_tool=[],
    )


def _extract_file_snippet_request(query: str) -> str | None:
    patterns = (
        r"read file\s+([^\n]+)$",
        r"show file\s+([^\n]+)$",
        r"open file\s+([^\n]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, query.strip(), flags=re.IGNORECASE)
        if match:
            return match.group(1).strip().strip("'\"")
    return None


def _normalize_code_search_query(query: str) -> str:
    lowered = query.lower()
    phrase_map = {
        "runtime status": "runtime_healthy",
        "meta query": "meta_query",
        "tool loader": "RuntimeToolsLoader",
        "orchestrator": "orchestrator",
        "kernel": "kernel",
        "tool runtime": "tools",
    }
    for phrase, token in phrase_map.items():
        if phrase in lowered:
            return token

    stopwords = {
        "where", "what", "which", "file", "code", "server", "show",
        "find", "implemented", "located", "is", "the", "in", "for",
    }
    tokens = [tok for tok in re.findall(r"[a-zA-Z_]{3,}", lowered) if tok not in stopwords]
    if not tokens:
        return query
    return tokens[0]


def _extract_tool_name(query: str) -> str | None:
    normalized = query.lower()
    tool_names = [tool["name"] for tool in get_tool_catalog_service().summary().get("tools", [])]
    for name in tool_names:
        if name.lower() in normalized or name.replace("_", " ").lower() in normalized:
            return name
    return None

