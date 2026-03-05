from __future__ import annotations

import re
from typing import Optional

from app.agent.runtime.meta_tools import (
    capability_snapshot_lookup,
    kernel_best_tools_lookup,
    kernel_history_lookup,
    kernel_log_lookup,
    kernel_success_rate_lookup,
    kernel_tool_inventory_lookup,
    repo_read_snippet_lookup,
    repo_search_lookup,
)
from app.models.pqh_response_model import CognitiveState, PQHResponse


def is_meta_query(query: str) -> bool:
    text = query.lower()
    indicators = (
        "what task",
        "tasks did",
        "history",
        "success rate",
        "how many tools",
        "tools do we have",
        "client tools",
        "server tools",
        "tool status",
        "status of tools",
        "their status",
        "best tools",
        "what can you do",
        "capabilities",
        "limitation",
        "codebase",
        "source code",
        "server code",
        "where is",
        "which file",
        "logs",
        "error trace",
    )
    return any(token in text for token in indicators)


async def try_handle_meta_query(query: str, user_id: str) -> Optional[PQHResponse]:
    text = query.lower()

    if "success rate" in text:
        data = await kernel_success_rate_lookup(user_id=user_id)
        answer = (
            f"In the last {data['window_days']} days: total tasks={data['total_tasks']}, "
            f"completed={data['completed']}, failed={data['failed']}, "
            f"success rate={data['success_rate']}%."
        )
        return _response(query, answer)

    if (
        "how many tools" in text
        or "tool count" in text
        or "tool status" in text
        or "client tools" in text
        or "server tools" in text
        or "their status" in text
        or "status of tools" in text
        or "tools do we have" in text
    ):
        data = await kernel_tool_inventory_lookup(user_id=user_id)
        runtime_health = "healthy" if data.get("runtime_healthy") else "unhealthy"
        answer = (
            f"Runtime tools loaded: {data['total_tools']} total "
            f"({data['server_tools']} server, {data['client_tools']} client). "
            f"Runtime status: {runtime_health}, sync={data.get('runtime_sync_status', 'unknown')}."
        )
        return _response(query, answer)

    if "best tools" in text:
        data = await kernel_best_tools_lookup(user_id=user_id, limit=5)
        items = data.get("items", [])
        if not items:
            return _response(query, "No tool usage data available yet for this user.")
        labels = [f"{item['tool_name']} ({item['weighted_score']})" for item in items]
        return _response(query, "Top tools by weighted score: " + ", ".join(labels))

    if "what can you do" in text or "capabilities" in text or "limitation" in text:
        data = await capability_snapshot_lookup(user_id=user_id)
        limitations = data.get("limitations", [])
        runtime = data.get("runtime", {})
        answer = (
            f"I currently have {runtime.get('total_tools', 0)} runtime tools "
            f"({runtime.get('server_tools', 0)} server / {runtime.get('client_tools', 0)} client), "
            f"environment={data.get('environment', 'unknown')}. "
            f"Limitations: {'; '.join(limitations[:3])}"
        )
        return _response(query, answer)

    if "log" in text or "error trace" in text:
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
        search_query = _normalize_code_search_query(query)
        data = await repo_search_lookup(user_id=user_id, query=search_query, limit=5, max_bytes=8000)
        items = data.get("items", [])
        if not items:
            return _response(query, data.get("summary", "No matching code context found."))
        formatted = [f"{item['path']}:{item['line']} -> {item['snippet']}" for item in items[:3]]
        answer = data.get("summary", "Code matches found.") + " Top matches: " + " | ".join(formatted)
        return _response(query, answer)

    if "task" in text or "history" in text:
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
        "runtime sync": "runtime_sync",
        "meta query": "meta_query",
        "tool loader": "RuntimeToolsLoader",
        "orchestrator": "orchestrator",
        "kernel": "kernel",
        "tools plugin": "tools_plugin",
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

