"""
"Today's Follow-up" — per-day task list that persists and supports check-off.

Stored as `{user_data_dir}/followup/{YYYY-MM-DD}.json`.
Organize_day auto-suggests tasks; the user can add, toggle, and delete tasks.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.path.manager import PathManager
from app.plugins.tools.tool_base import BaseTool, ToolOutput

logger = logging.getLogger(__name__)


# ── Storage helpers ──────────────────────────────────────────────────────────

def _followup_dir() -> Path:
    pm = PathManager()
    dir_path = pm.get_user_data_dir() / "followup"
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path


def _today_path() -> Path:
    return _followup_dir() / f"{date.today().isoformat()}.json"


def _path_for(day: str) -> Path:
    return _followup_dir() / f"{day}.json"


def _load_tasks(day: Optional[str] = None) -> List[Dict[str, Any]]:
    path = _path_for(day) if day else _today_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_tasks(tasks: List[Dict[str, Any]], day: Optional[str] = None) -> None:
    path = _path_for(day) if day else _today_path()
    path.write_text(
        json.dumps(tasks, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _task_id() -> str:
    return uuid.uuid4().hex[:12]


# ── Tool ──────────────────────────────────────────────────────────────────────

class TodayFollowupTool(BaseTool):
    """
    Manage a per-day follow-up task list.

    Actions:
      - "list"        → get all tasks for today (or a specific date)
      - "add"         → add a new task
      - "toggle"      → toggle a task's completed status
      - "delete"      → remove a task by id
      - "suggest"     → add a batch of suggested tasks (from organize_day)
    """

    TOOL_DESCRIPTION = "Manage today's follow-up task list — add tasks, mark them complete, or review what's pending"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA = {
        "action": {
            "type": "string",
            "required": True,
            "enum": ["list", "add", "toggle", "delete", "suggest"],
            "description": "Operation to perform",
        },
        "task_id": {
            "type": "string",
            "required": False,
            "description": "Task ID (required for toggle/delete)",
        },
        "text": {
            "type": "string",
            "required": False,
            "description": "Task description (required for add/suggest)",
        },
        "priority": {
            "type": "string",
            "required": False,
            "enum": ["high", "medium", "low"],
            "description": "Task priority (default: medium)",
        },
        "source": {
            "type": "string",
            "required": False,
            "description": "Source tool name (default: manual)",
        },
        "tasks": {
            "type": "array",
            "required": False,
            "description": "Batch of tasks for 'suggest' action: [{'text': '...', 'priority': 'medium', 'source': '...'}]",
        },
        "date": {
            "type": "string",
            "required": False,
            "description": "Date in YYYY-MM-DD format (defaults to today)",
        },
    }
    OUTPUT_SCHEMA = {
        "success": {"type": "boolean"},
        "data": {
            "tasks": {"type": "array"},
            "count": {"type": "integer"},
            "completed": {"type": "integer"},
            "pending": {"type": "integer"},
            "message": {"type": "string"},
        },
        "error": {"type": "string"},
    }
    EXAMPLES = [
        {"user_utterance": "show my follow-up tasks"},
        {"user_utterance": "add a task to review the proposal"},
        {"user_utterance": "mark the first task as done"},
    ]
    SEMANTIC_TAGS = ["task", "followup", "today", "todo", "checklist"]
    TOOL_CATEGORY = "productivity"
    METADATA: Dict[str, Any] = {"summary_tts": False}

    def get_tool_name(self) -> str:
        return "today_followup"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        action = str(inputs.get("action") or "list").strip().lower()

        try:
            if action == "list":
                return self._list_tasks(inputs)
            if action == "add":
                return self._add_task(inputs)
            if action == "toggle":
                return self._toggle_task(inputs)
            if action == "delete":
                return self._delete_task(inputs)
            if action == "suggest":
                return self._suggest_tasks(inputs)
            return ToolOutput(success=False, data={}, error=f"Unknown action: {action}")
        except Exception as e:
            logger.error("today_followup error: %s", e)
            return ToolOutput(success=False, data={}, error=str(e))

    def _list_tasks(self, inputs: Dict[str, Any]) -> ToolOutput:
        day = str(inputs.get("date") or "").strip() or None
        tasks = _load_tasks(day)
        completed = sum(1 for t in tasks if t.get("completed"))
        pending = len(tasks) - completed
        return ToolOutput(
            success=True, data={
                "tasks": tasks,
                "count": len(tasks),
                "completed": completed,
                "pending": pending,
                "message": f"{pending} pending, {completed} completed" if tasks else "No tasks for today",
            }
        )

    def _add_task(self, inputs: Dict[str, Any]) -> ToolOutput:
        text = str(inputs.get("text") or "").strip()
        if not text:
            return ToolOutput(success=False, data={}, error="Task text is required")

        day = str(inputs.get("date") or "").strip() or None
        tasks = _load_tasks(day)
        task = {
            "id": _task_id(),
            "text": text,
            "completed": False,
            "priority": str(inputs.get("priority") or "medium").strip().lower(),
            "source": str(inputs.get("source") or "manual").strip(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        tasks.append(task)
        _save_tasks(tasks, day)

        completed = sum(1 for t in tasks if t.get("completed"))
        pending = len(tasks) - completed
        return ToolOutput(
            success=True, data={
                "tasks": tasks,
                "count": len(tasks),
                "completed": completed,
                "pending": pending,
                "message": f"Added: {text}",
            }
        )

    def _toggle_task(self, inputs: Dict[str, Any]) -> ToolOutput:
        task_id = str(inputs.get("task_id") or "").strip()
        if not task_id:
            return ToolOutput(success=False, data={}, error="task_id is required")

        day = str(inputs.get("date") or "").strip() or None
        tasks = _load_tasks(day)
        found = False
        for task in tasks:
            if task.get("id") == task_id:
                task["completed"] = not task.get("completed", False)
                task["updated_at"] = datetime.now(timezone.utc).isoformat()
                found = True
                break

        if not found:
            return ToolOutput(success=False, data={}, error=f"Task not found: {task_id}")

        _save_tasks(tasks, day)
        completed = sum(1 for t in tasks if t.get("completed"))
        pending = len(tasks) - completed
        return ToolOutput(
            success=True, data={
                "tasks": tasks,
                "count": len(tasks),
                "completed": completed,
                "pending": pending,
                "message": f"Task toggled — {pending} pending, {completed} completed",
            }
        )

    def _delete_task(self, inputs: Dict[str, Any]) -> ToolOutput:
        task_id = str(inputs.get("task_id") or "").strip()
        if not task_id:
            return ToolOutput(success=False, data={}, error="task_id is required")

        day = str(inputs.get("date") or "").strip() or None
        tasks = _load_tasks(day)
        before = len(tasks)
        tasks = [t for t in tasks if t.get("id") != task_id]

        if len(tasks) == before:
            return ToolOutput(success=False, data={}, error=f"Task not found: {task_id}")

        _save_tasks(tasks, day)
        completed = sum(1 for t in tasks if t.get("completed"))
        pending = len(tasks) - completed
        return ToolOutput(
            success=True, data={
                "tasks": tasks,
                "count": len(tasks),
                "completed": completed,
                "pending": pending,
                "message": "Task deleted",
            }
        )

    def _suggest_tasks(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Batch-add suggested tasks (called by organize_day or other tools)."""
        raw_tasks = inputs.get("tasks", [])
        if not raw_tasks or not isinstance(raw_tasks, list):
            return ToolOutput(success=False, data={}, error="No tasks provided")

        day = str(inputs.get("date") or "").strip() or None
        existing = _load_tasks(day)
        existing_texts = {t.get("text", "").strip().lower() for t in existing}

        added = 0
        for suggestion in raw_tasks:
            text = str(suggestion.get("text") or "").strip()
            if not text:
                continue
            # Deduplicate by text
            if text.lower() in existing_texts:
                continue
            existing_texts.add(text.lower())
            existing.append({
                "id": _task_id(),
                "text": text,
                "completed": False,
                "priority": str(suggestion.get("priority") or "medium").strip().lower(),
                "source": str(suggestion.get("source") or "organize_day").strip(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            added += 1

        if added > 0:
            _save_tasks(existing, day)

        completed = sum(1 for t in existing if t.get("completed"))
        pending = len(existing) - completed
        return ToolOutput(
            success=True, data={
                "tasks": existing,
                "count": len(existing),
                "completed": completed,
                "pending": pending,
                "message": f"Added {added} suggested task(s)" if added else "No new tasks to add",
            }
        )


__all__ = ["TodayFollowupTool"]
