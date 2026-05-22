"""
DAG Replanner — Patch-based task graph mutation with validation.

The replanner receives a structured prompt with execution state,
asks the LLM for a diff-based patch, validates it against the DAG,
and applies mutations transactionally.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.kernel.execution.execution_models import (
    ExecutionState, Task, TaskRecord, TaskOutput, TaskStatus,
)

logger = logging.getLogger(__name__)


# ── Budget Settings ─────────────────────────────────────────────────────────────

MAX_REPLANS_PER_JOB = 3
MAX_REPLANS_PER_TASK = 1    # Tracked via lineage_id across replacements
MAX_TOKENS_PER_JOB = 50000  # Cumulative planner + replanner tokens (not tool-internal)


# ── Diff Operations ─────────────────────────────────────────────────────────────

class DiffValidationError(Exception):
    """Raised when a diff cannot be safely applied to the DAG."""
    pass


def validate_diff(state: ExecutionState, diff_ops: List[Dict[str, Any]]) -> None:
    """
    Validate that diff_ops can be safely applied without corrupting the DAG.

    Raises DiffValidationError on:
      - target_task_id references that don't exist
      - Operations that would create cycles
      - Orphaned tasks
    """
    # Work on a copy to avoid side effects
    temp_tasks = copy.deepcopy(state.tasks)

    for op in diff_ops:
        op_type = op.get("op")

        if op_type == "insert_before":
            target = op.get("target_task_id")
            if target not in temp_tasks:
                raise DiffValidationError(f"insert_before target '{target}' not found in DAG")
            new_tasks = op.get("tasks", [])
            for nt in new_tasks:
                tid = nt.get("task_id")
                if tid in temp_tasks:
                    raise DiffValidationError(f"insert_before would create duplicate task_id '{tid}'")
                # Add placeholder for cycle check
                temp_tasks[tid] = _placeholder_record(nt)
            # Update target's depends_on to include new tasks
            target_rec = temp_tasks[target]
            new_deps = [nt.get("task_id") for nt in new_tasks]
            target_rec.task.depends_on = list(set(target_rec.task.depends_on + new_deps))

        elif op_type == "replace":
            target = op.get("target_task_id")
            if target not in temp_tasks:
                raise DiffValidationError(f"replace target '{target}' not found in DAG")
            # Replace preserves the same task_id (Static ID Rule)
            replacement = op.get("with", {})
            old_rec = temp_tasks[target]
            old_rec.task.tool = replacement.get("tool", old_rec.task.tool)
            old_rec.task.inputs = replacement.get("inputs", old_rec.task.inputs)

        elif op_type == "retry":
            target = op.get("target_task_id")
            if target not in temp_tasks:
                raise DiffValidationError(f"retry target '{target}' not found in DAG")

        elif op_type == "delete":
            targets = op.get("target_task_ids", [])
            for tid in targets:
                if tid not in temp_tasks:
                    raise DiffValidationError(f"delete target '{tid}' not found in DAG")
                del temp_tasks[tid]
            # Clean up dangling depends_on references
            for rec in temp_tasks.values():
                rec.task.depends_on = [d for d in rec.task.depends_on if d not in targets]

        else:
            raise DiffValidationError(f"Unknown diff op: {op_type}")

    # Cycle check via topological sort (Kahn's algorithm)
    if _has_cycles(temp_tasks):
        raise DiffValidationError("Mutated DAG contains a cycle")


def apply_diff(state: ExecutionState, diff_ops: List[Dict[str, Any]]) -> None:
    """
    Apply validated diff operations to the live ExecutionState.
    MUST call validate_diff first.
    """
    for op in diff_ops:
        op_type = op["op"]

        if op_type == "insert_before":
            target_id = op["target_task_id"]
            new_tasks = op.get("tasks", [])
            new_ids = []
            for nt_dict in new_tasks:
                task = Task(**nt_dict)
                record = TaskRecord(task=task, status="pending")
                state.add_task(record)
                new_ids.append(task.task_id)
                logger.info("[Replanner] Inserted task %s before %s", task.task_id, target_id)
            # Wire the target to depend on inserted tasks
            target_rec = state.get_task(target_id)
            if target_rec:
                target_rec.task.depends_on = list(set(target_rec.task.depends_on + new_ids))

        elif op_type == "replace":
            target_id = op["target_task_id"]
            replacement = op.get("with", {})
            rec = state.get_task(target_id)
            if rec:
                # Static ID Rule: preserve task_id
                if "tool" in replacement:
                    rec.task.tool = replacement["tool"]
                if "inputs" in replacement:
                    rec.task.inputs = replacement["inputs"]
                if "execution_target" in replacement:
                    rec.task.execution_target = replacement["execution_target"]
                # Reset execution state
                rec.status = "pending"
                rec.error = None
                rec.output = None
                rec.started_at = None
                rec.completed_at = None
                rec.duration_ms = None
                logger.info("[Replanner] Replaced task %s (tool=%s)", target_id, rec.task.tool)

        elif op_type == "retry":
            target_id = op["target_task_id"]
            rec = state.get_task(target_id)
            if rec:
                rec.status = "pending"
                rec.error = None
                rec.output = None
                rec.started_at = None
                rec.completed_at = None
                rec.duration_ms = None
                logger.info("[Replanner] Reset task %s for retry", target_id)

        elif op_type == "delete":
            targets = op.get("target_task_ids", [])
            for tid in targets:
                if tid in state.tasks:
                    del state.tasks[tid]
                    logger.info("[Replanner] Deleted task %s", tid)
            # Clean up dependencies
            for rec in state.tasks.values():
                rec.task.depends_on = [d for d in rec.task.depends_on if d not in targets]


def unblock_dependents(state: ExecutionState, resolved_task_id: str) -> List[str]:
    """
    After a failed task is successfully repaired/retried, transition
    its blocked dependents back to pending if all their dependencies are now met.

    Returns list of unblocked task_ids.
    """
    unblocked = []
    completed_ids = state.get_completed_task_ids()
    # Also consider pending tasks that were just reset (they aren't blocking)
    non_blocking = set(completed_ids)
    for rec in state.tasks.values():
        if rec.status in ("pending", "running", "emitted", "waiting"):
            non_blocking.add(rec.task_id)

    for rec in state.tasks.values():
        if rec.status != "blocked":
            continue
        # Check if all dependencies are non-blocking now
        all_met = all(dep in non_blocking for dep in rec.task.depends_on)
        if all_met:
            rec.status = "pending"
            rec.error = None
            unblocked.append(rec.task_id)
            logger.info("[Replanner] Unblocked task %s", rec.task_id)

    return unblocked


# ── Replanner Prompt Builder ────────────────────────────────────────────────────

def build_replan_prompt(
    original_query: str,
    failed_task: TaskRecord,
    state: ExecutionState,
    available_tools: List[str],
    budget_remaining: Dict[str, Any],
    compact_fn: Optional[Callable] = None,
    active_locks: Optional[List[str]] = None,
    other_jobs: Optional[List[Dict[str, str]]] = None,
) -> List[Dict[str, str]]:
    """
    Build the structured LLM prompt for the replanner.
    Returns messages list for the LLM call.
    """
    # Compact function for summarizing outputs
    def _compact(data: Any) -> Any:
        if compact_fn:
            return compact_fn(data)
        if isinstance(data, dict):
            return {k: str(v)[:200] for k, v in list(data.items())[:6]}
        return str(data)[:500]

    completed_tasks = []
    for rec in state.tasks.values():
        if rec.status == "completed" and rec.output:
            completed_tasks.append({
                "task_id": rec.task_id,
                "tool": rec.tool,
                "summary_output": _compact(rec.output.data) if rec.output else {},
            })

    blocked_tasks = [
        {"task_id": rec.task_id, "tool": rec.tool}
        for rec in state.tasks.values() if rec.status == "blocked"
    ]

    remaining_tasks = [
        {"task_id": rec.task_id, "tool": rec.tool}
        for rec in state.tasks.values() if rec.status == "pending"
    ]

    replan_context = {
        "original_query": original_query,
        "failed_task": {
            "task_id": failed_task.task_id,
            "tool": failed_task.tool,
            "inputs": failed_task.task.inputs,
        },
        "error_details": {
            "category": "recoverable",
            "error_message": failed_task.error or "Unknown error",
        },
        "completed_tasks": completed_tasks,
        "blocked_tasks": blocked_tasks,
        "remaining_tasks": remaining_tasks,
        "available_tools": available_tools,
        "active_resource_locks": active_locks or [],
        "other_active_jobs": other_jobs or [],
        "budget_remaining": budget_remaining,
    }

    system_prompt = """You are a task execution replanner. A task in an execution plan has failed.
Your job is to emit a JSON diff that patches the task DAG to recover from the failure.

Available diff operations:
- {"op": "insert_before", "target_task_id": "<id>", "tasks": [<Task objects>]}
  Inserts new tasks before the target. The target will depend on the new tasks.
- {"op": "replace", "target_task_id": "<id>", "with": {"tool": "...", "inputs": {...}}}
  Replaces the tool/inputs of the target task. The task_id is preserved.
- {"op": "retry", "target_task_id": "<id>"}
  Resets the failed task to pending so it re-runs (use after insert_before adds a fix).
- {"op": "delete", "target_task_ids": ["<id>", ...]}
  Removes tasks from the DAG.

Rules:
- Return ONLY a JSON object: {"diff": [...operations...]}
- Do NOT change task_ids on replace — the original task_id is preserved.
- Prefer minimal changes. Insert a fix task + retry over replacing the whole plan.
- If the error is clearly unrecoverable (e.g. the tool fundamentally cannot do this), return {"diff": []} (empty).
- Do not invent tools that are not in the available_tools list.
- Each inserted task needs: task_id, tool, execution_target ("server" or "client"), inputs.
"""

    user_prompt = f"""Execution context:
{json.dumps(replan_context, indent=2, ensure_ascii=False)}

Emit the recovery diff now. Return ONLY raw JSON."""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def parse_replan_response(raw_response: str) -> List[Dict[str, Any]]:
    """
    Parse the LLM's raw response into a list of diff operations.
    Returns empty list if parsing fails.
    """
    text = raw_response.strip()

    # Strip markdown fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed.get("diff", [])
        return []
    except json.JSONDecodeError:
        logger.error("[Replanner] Failed to parse LLM response as JSON: %s", text[:200])
        return []


# ── Internal Helpers ────────────────────────────────────────────────────────────

def _placeholder_record(task_dict: Dict[str, Any]) -> TaskRecord:
    """Create a placeholder TaskRecord for validation purposes."""
    task = Task(
        task_id=task_dict.get("task_id", "unknown"),
        tool=task_dict.get("tool", "unknown"),
        execution_target=task_dict.get("execution_target", "server"),
        depends_on=task_dict.get("depends_on", []),
        inputs=task_dict.get("inputs", {}),
    )
    return TaskRecord(task=task, status="pending")


def _has_cycles(tasks: Dict[str, TaskRecord]) -> bool:
    """Detect cycles using Kahn's algorithm."""
    in_degree: Dict[str, int] = {tid: 0 for tid in tasks}
    adj: Dict[str, List[str]] = {tid: [] for tid in tasks}

    for tid, rec in tasks.items():
        for dep in rec.task.depends_on:
            if dep in adj:
                adj[dep].append(tid)
                in_degree[tid] += 1

    queue = [tid for tid, deg in in_degree.items() if deg == 0]
    visited = 0

    while queue:
        node = queue.pop(0)
        visited += 1
        for neighbor in adj.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    return visited != len(tasks)
