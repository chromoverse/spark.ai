"""
Execution Watcher — wraps task execution with auto-retry and recovery.

The watcher observes each task execution and:
1. Detects failures and checks if they're retryable
2. Retries with modified inputs when possible
3. Looks at predecessor outputs to fix missing bindings
4. Emits humanistic status messages via WebSocket
5. Reports clear failure reasons when recovery isn't possible
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional

from app.agent.runtime.tool_context_service import get_tool_context_service
from app.kernel.execution.execution_models import TaskRecord, TaskOutput

logger = logging.getLogger(__name__)

MAX_RETRIES = 2


class WatcherResult:
    __slots__ = ("output", "retries_used", "recovered", "watcher_message")

    def __init__(
        self,
        output: TaskOutput,
        retries_used: int = 0,
        recovered: bool = False,
        watcher_message: Optional[str] = None,
    ):
        self.output = output
        self.retries_used = retries_used
        self.recovered = recovered
        self.watcher_message = watcher_message


def _try_resolve_missing_from_predecessors(
    task: TaskRecord,
    resolved_inputs: Dict[str, Any],
    error: str,
    get_task_output_fn: Optional[Callable[[str], Optional[TaskOutput]]],
) -> Optional[Dict[str, Any]]:
    """If a required param is missing, try to find it in predecessor outputs.

    Common case: file_open needs 'path' but binding failed. We look at
    depends_on tasks' outputs for fields like file_path, path, absolute_path.
    """
    if not get_task_output_fn:
        return None

    error_lower = error.lower()

    # Detect which param is missing
    missing_param = None
    if "missing required parameter:" in error_lower:
        missing_param = error_lower.split("missing required parameter:")[-1].strip()
    elif "path is required" in error_lower:
        missing_param = "path"
    elif "is required" in error_lower:
        # Try to extract: "X is required"
        parts = error_lower.split("is required")[0].strip().split()
        if parts:
            missing_param = parts[-1]

    if not missing_param:
        return None

    # Search predecessor outputs for a matching value
    path_aliases = ["file_path", "path", "absolute_path", "data_dir", "output_path"]
    search_keys = path_aliases if missing_param == "path" else [missing_param]

    for dep_id in (task.depends_on or []):
        dep_output = get_task_output_fn(dep_id)
        if not dep_output or not dep_output.data:
            continue
        for key in search_keys:
            val = dep_output.data.get(key)
            if val and isinstance(val, str) and val.strip():
                logger.info(
                    "🔧 Watcher: resolved missing '%s' from %s.data.%s = '%s'",
                    missing_param, dep_id, key, val,
                )
                patched = dict(resolved_inputs)
                patched[missing_param] = val
                return patched

    return None



async def _llm_diagnose_and_fix(
    task: TaskRecord,
    current_inputs: Dict[str, Any],
    error: str,
    get_task_output_fn: Optional[Callable[[str], Optional[TaskOutput]]],
) -> Optional[Dict[str, Any]]:
    """Use LLM to diagnose the error and suggest fixed inputs."""
    import json

    # Gather predecessor outputs for context
    predecessor_data = {}
    if get_task_output_fn and task.depends_on:
        for dep_id in task.depends_on:
            dep_out = get_task_output_fn(dep_id)
            if dep_out and dep_out.data:
                predecessor_data[dep_id] = dep_out.data

    # Build a compact prompt
    prompt = f"""A tool execution failed. Diagnose and fix the inputs.

TOOL: {task.tool}
ERROR: {error}
CURRENT INPUTS: {json.dumps({k:v for k,v in current_inputs.items() if not k.startswith('_')}, default=str)}
PREDECESSOR OUTPUTS: {json.dumps(predecessor_data, default=str)[:2000]}

Rules:
- The error is likely a wrong input format or missing/mismatched field name.
- Look at predecessor outputs and map the correct values to the tool's expected inputs.
- Return ONLY a JSON object with the fixed inputs (only the keys that need changing).
- If you cannot fix it, return {{}}.

OUTPUT (strict JSON, no explanation):"""

    try:
        from app.ai.providers.router import routed_chat
        raw, _ = await routed_chat("lightweight", messages=[{"role": "user", "content": prompt}], temperature=0.0, max_tokens=300)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
        fixes = json.loads(raw)
        if fixes and isinstance(fixes, dict):
            patched = dict(current_inputs)
            patched.update(fixes)
            logger.info(f"🧠 LLM diagnosed fix for {task.tool}: {list(fixes.keys())}")
            return patched
    except Exception as e:
        logger.debug(f"LLM diagnosis failed for {task.tool}: {e}")

    return None


async def watched_execute(
    user_id: str,
    task: TaskRecord,
    resolved_inputs: Dict[str, Any],
    executor_fn: Callable[[TaskRecord, Dict[str, Any]], Coroutine[Any, Any, TaskOutput]],
    *,
    max_retries: int = MAX_RETRIES,
    on_retry: Optional[Callable[[str, int, str], Coroutine[Any, Any, None]]] = None,
    get_task_output_fn: Optional[Callable[[str], Optional[TaskOutput]]] = None,
) -> WatcherResult:
    """Execute a task with automatic retry/recovery.

    Args:
        user_id: Owner of the execution.
        task: The task record.
        resolved_inputs: Already-resolved inputs dict.
        executor_fn: Async callable(task, inputs) -> TaskOutput.
        max_retries: Max retry attempts.
        on_retry: Optional callback(user_id, attempt, message) for status updates.
        get_task_output_fn: Optional callable(task_id) -> TaskOutput for predecessor lookup.

    Returns:
        WatcherResult with final output and metadata.
    """
    ctx = get_tool_context_service()
    last_output: Optional[TaskOutput] = None
    current_inputs = dict(resolved_inputs)

    for attempt in range(1 + max_retries):
        try:
            output = await executor_fn(task, current_inputs)
        except Exception as exc:
            output = TaskOutput(success=False, data={}, error=str(exc))

        if output.success:
            return WatcherResult(
                output=output,
                retries_used=attempt,
                recovered=attempt > 0,
                watcher_message=f"Recovered after {attempt} retry(s)" if attempt > 0 else None,
            )

        last_output = output
        error = output.error or "Unknown error"

        if attempt >= max_retries:
            break

        # Strategy 1: Try to resolve missing inputs from predecessor outputs
        patched = _try_resolve_missing_from_predecessors(
            task, current_inputs, error, get_task_output_fn,
        )
        if patched:
            current_inputs = patched
            msg = f"⟳ Watcher: resolved missing input from predecessor, retrying {task.tool}"
            logger.info(msg)
            if on_retry:
                await on_retry(user_id, attempt + 1, msg)
            await asyncio.sleep(0.1)
            continue

        # Strategy 2: LLM-assisted error diagnosis — ask LLM to fix inputs
        patched_by_llm = await _llm_diagnose_and_fix(task, current_inputs, error, get_task_output_fn)
        if patched_by_llm:
            current_inputs = patched_by_llm
            msg = f"⟳ Watcher: LLM diagnosed error and patched inputs, retrying {task.tool}"
            logger.info(msg)
            if on_retry:
                await on_retry(user_id, attempt + 1, msg)
            await asyncio.sleep(0.1)
            continue

        # Strategy 3: Check standard retry rules
        strategy = ctx.suggest_retry_strategy(user_id, task.task_id, task.tool, error)

        if not strategy.get("should_retry"):
            break

        if strategy.get("modified_inputs"):
            current_inputs.update(strategy["modified_inputs"])

        msg = f"⟳ Retrying {task.tool} (attempt {attempt + 2}/{1 + max_retries}): {strategy.get('suggestion', '')}"
        logger.info(msg)

        if on_retry:
            await on_retry(user_id, attempt + 1, msg)

        await asyncio.sleep(0.3 * (attempt + 1))

    # All retries exhausted
    return WatcherResult(
        output=last_output or TaskOutput(success=False, data={}, error="Execution failed"),
        retries_used=max_retries,
        recovered=False,
        watcher_message=_humanize_failure(task.tool, last_output.error if last_output else "Unknown error"),
    )


def _humanize_failure(tool_name: str, error: str) -> str:
    """Generate a human-friendly failure message."""
    error_lower = (error or "").lower()
    tool_label = tool_name.replace("_", " ")

    if "not found" in error_lower or "enoent" in error_lower:
        return f"Couldn't find what was needed for {tool_label}. The file or path doesn't exist."
    if "permission" in error_lower:
        return f"Don't have permission to complete {tool_label}. Try a different location."
    if "timed out" in error_lower:
        return f"The {tool_label} took too long and timed out."
    if "dependency not completed" in error_lower:
        return f"A previous step didn't finish in time, so {tool_label} couldn't proceed."
    if "connection" in error_lower or "econnrefused" in error_lower:
        return f"Couldn't connect to the required service for {tool_label}."
    if "already exists" in error_lower:
        return f"The target already exists. Use overwrite if you want to replace it."
    if "path is required" in error_lower:
        return f"The {tool_label} step couldn't determine the file path from the previous step."

    return f"The {tool_label} step ran into an issue: {error[:120]}"
