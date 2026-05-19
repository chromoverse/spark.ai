"""Tool Context Service — execution-time memory, error recovery, process tracking.

This service runs DURING execution (not at planning time) to give the
ExecutionEngine and individual tools awareness of:
- Recent tool outputs (so follow-up tasks can reference prior results)
- Error patterns and retry suggestions
- Active long-running processes spawned by tools like shell_agent

This is the "smart layer" that sits between the orchestrator and tool execution.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ProcessInfo:
    """Metadata for a tracked long-running process."""

    pid: int
    command: str
    task_id: str
    tool_name: str
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    status: str = "running"  # running | exited | unknown


@dataclass
class ToolOutputRecord:
    """Compact record of a tool execution result for session memory."""

    task_id: str
    tool_name: str
    success: bool
    created_at: str
    data_summary: Dict[str, Any]  # compact subset of output.data
    error: Optional[str] = None


@dataclass
class AppStateRecord:
    """Tracked readiness state for an app that tools depend on."""

    app_name: str
    pid: int = 0
    status: str = "unknown"  # unknown | launching | window_found | focused | ready | timeout | focus_failed
    launched_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_checked_at: str = field(default_factory=lambda: datetime.now().isoformat())
    window_title: str = ""
    focused: bool = False
    ready: bool = False
    ready_checks: int = 0
    last_reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


# ── Retry heuristics ─────────────────────────────────────────────────────────

_RETRY_RULES: List[Dict[str, Any]] = [
    {
        "pattern": "ENOENT",
        "reason": "File or directory not found",
        "suggestion": "Check working directory or create parent folders first.",
        "should_retry": False,
    },
    {
        "pattern": "PermissionError",
        "reason": "Permission denied",
        "suggestion": "Try a different path (e.g. user artifacts directory).",
        "should_retry": False,
    },
    {
        "pattern": "timed out",
        "reason": "Command timed out",
        "suggestion": "Increase timeout or break into smaller steps.",
        "should_retry": True,
        "modify": {"timeout_ms": 60000},
    },
    {
        "pattern": "ECONNREFUSED",
        "reason": "Connection refused",
        "suggestion": "Check if a required service is running.",
        "should_retry": True,
    },
    {
        "pattern": "ModuleNotFoundError",
        "reason": "Missing Python module",
        "suggestion": "Install the required package first.",
        "should_retry": False,
    },
    {
        "pattern": "npm ERR!",
        "reason": "npm error",
        "suggestion": "Check package.json or clear npm cache.",
        "should_retry": True,
    },
]


class ToolContextService:
    """Execution-time context for tools — memory, error recovery, process tracking.

    This is NOT the SQH planning layer. This runs DURING execution to help
    the ExecutionEngine and individual tools make smarter decisions.
    """

    def __init__(self, max_history: int = 20):
        self._max_history = max_history
        # Per-user session memory
        self._recent_outputs: Dict[str, Deque[ToolOutputRecord]] = {}
        # Per-user active processes
        self._active_processes: Dict[str, Dict[str, ProcessInfo]] = {}
        # Per-user app readiness state
        self._app_states: Dict[str, Dict[str, AppStateRecord]] = {}
        self._process_manager: Any = None

    # ── Tool output memory ───────────────────────────────────────────────

    def record_tool_output(
        self,
        user_id: str,
        task_id: str,
        tool_name: str,
        output_data: Dict[str, Any],
        success: bool,
        error: Optional[str] = None,
    ) -> None:
        """Record a tool output for short-term session memory."""
        if user_id not in self._recent_outputs:
            self._recent_outputs[user_id] = deque(maxlen=self._max_history)

        # Build compact summary (keep only scalar values + short strings)
        summary: Dict[str, Any] = {}
        for key, value in (output_data or {}).items():
            if isinstance(value, (int, float, bool)):
                summary[key] = value
            elif isinstance(value, str) and len(value) <= 300:
                summary[key] = value
            elif isinstance(value, str):
                summary[key] = value[:200] + "..."
            elif isinstance(value, list):
                summary[key] = f"[{len(value)} items]"
            elif isinstance(value, dict):
                summary[key] = f"{{{len(value)} fields}}"

        record = ToolOutputRecord(
            task_id=task_id,
            tool_name=tool_name,
            success=success,
            created_at=datetime.now().isoformat(),
            data_summary=summary,
            error=error,
        )
        self._recent_outputs[user_id].append(record)
        logger.debug(
            "Recorded output for user=%s task=%s tool=%s success=%s",
            user_id,
            task_id,
            tool_name,
            success,
        )

    def get_recent_outputs(self, user_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Return the last N tool outputs for this user's session."""
        history = self._recent_outputs.get(user_id, deque())
        items = list(history)[-limit:]
        return [
            {
                "task_id": r.task_id,
                "tool_name": r.tool_name,
                "success": r.success,
                "created_at": r.created_at,
                "data_summary": r.data_summary,
                "error": r.error,
            }
            for r in items
        ]

    # ── Error analysis / retry suggestions ───────────────────────────────

    def suggest_retry_strategy(
        self,
        user_id: str,
        task_id: str,
        tool_name: str,
        error: str,
    ) -> Dict[str, Any]:
        """Analyze an error and suggest retry/recovery.

        Returns::

            {
                "should_retry": bool,
                "reason": str,
                "suggestion": str,
                "modified_inputs": dict | None,
            }
        """
        error_lower = (error or "").lower()

        for rule in _RETRY_RULES:
            if rule["pattern"].lower() in error_lower:
                return {
                    "should_retry": rule["should_retry"],
                    "reason": rule["reason"],
                    "suggestion": rule["suggestion"],
                    "modified_inputs": rule.get("modify"),
                }

        # Check if we've seen this exact tool fail recently (repeated failure)
        recent = self._recent_outputs.get(user_id, deque())
        same_tool_failures = sum(
            1
            for r in recent
            if r.tool_name == tool_name and not r.success
        )
        if same_tool_failures >= 2:
            return {
                "should_retry": False,
                "reason": f"Tool '{tool_name}' has failed {same_tool_failures} times recently.",
                "suggestion": "Investigate root cause before retrying.",
                "modified_inputs": None,
            }

        return {
            "should_retry": False,
            "reason": "Unknown error pattern.",
            "suggestion": error[:200] if error else "No error details available.",
            "modified_inputs": None,
        }

    # ── Process tracking ─────────────────────────────────────────────────

    def register_process(
        self,
        user_id: str,
        task_id: str,
        tool_name: str,
        pid: int,
        command: str,
    ) -> None:
        """Track a spawned long-running process."""
        if user_id not in self._active_processes:
            self._active_processes[user_id] = {}

        proc_key = f"{task_id}:{pid}"
        self._active_processes[user_id][proc_key] = ProcessInfo(
            pid=pid,
            command=command,
            task_id=task_id,
            tool_name=tool_name,
        )
        logger.info(
            "Registered process pid=%d for user=%s task=%s cmd=%s",
            pid,
            user_id,
            task_id,
            command[:80],
        )

    def get_active_processes(self, user_id: str) -> List[Dict[str, Any]]:
        """Return all tracked processes for this user."""
        procs = self._active_processes.get(user_id, {})
        return [
            {
                "pid": p.pid,
                "command": p.command,
                "task_id": p.task_id,
                "tool_name": p.tool_name,
                "started_at": p.started_at,
                "status": p.status,
            }
            for p in procs.values()
        ]

    # ── App readiness tracking ────────────────────────────────────────────

    @staticmethod
    def _app_key(app_name: str) -> str:
        return str(app_name or "").strip().lower()

    def _get_process_manager(self):
        if self._process_manager is None:
            from tools.utils.process_manager.process_manager import ProcessManager
            self._process_manager = ProcessManager()
        return self._process_manager

    def record_app_launch(
        self,
        user_id: str,
        app_name: str,
        *,
        pid: int = 0,
        status: str = "launching",
        window_title: str = "",
        focused: bool = False,
        ready: bool = False,
        ready_checks: int = 0,
        reason: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Create or replace tracked launch state for an app."""
        key = self._app_key(app_name)
        if not key:
            return
        if user_id not in self._app_states:
            self._app_states[user_id] = {}

        existing = self._app_states[user_id].get(key)
        now = datetime.now().isoformat()
        merged_metadata = dict(existing.metadata) if existing else {}
        if metadata:
            merged_metadata.update(metadata)

        self._app_states[user_id][key] = AppStateRecord(
            app_name=str(app_name).strip() or key,
            pid=pid if isinstance(pid, int) and pid > 0 else (existing.pid if existing else 0),
            status=status,
            launched_at=existing.launched_at if existing else now,
            last_checked_at=now,
            window_title=window_title or (existing.window_title if existing else ""),
            focused=focused,
            ready=ready,
            ready_checks=ready_checks if ready_checks > 0 else (existing.ready_checks if existing else 0),
            last_reason=reason,
            metadata=merged_metadata,
        )

    def update_app_state(
        self,
        user_id: str,
        app_name: str,
        *,
        pid: Optional[int] = None,
        status: Optional[str] = None,
        window_title: Optional[str] = None,
        focused: Optional[bool] = None,
        ready: Optional[bool] = None,
        ready_checks: Optional[int] = None,
        reason: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Patch tracked app state without losing previous fields."""
        key = self._app_key(app_name)
        if not key:
            return
        if user_id not in self._app_states or key not in self._app_states[user_id]:
            self.record_app_launch(
                user_id=user_id,
                app_name=app_name,
                pid=pid or 0,
                status=status or "unknown",
                window_title=window_title or "",
                focused=bool(focused),
                ready=bool(ready),
                ready_checks=ready_checks or 0,
                reason=reason or "",
                metadata=metadata,
            )
            return

        record = self._app_states[user_id][key]
        record.last_checked_at = datetime.now().isoformat()
        if isinstance(pid, int) and pid > 0:
            record.pid = pid
        if status is not None:
            record.status = status
        if window_title is not None:
            record.window_title = window_title
        if focused is not None:
            record.focused = focused
        if ready is not None:
            record.ready = ready
        if ready_checks is not None:
            record.ready_checks = ready_checks
        if reason is not None:
            record.last_reason = reason
        if metadata:
            record.metadata.update(metadata)

    def get_app_state(self, user_id: str, app_name: str) -> Optional[Dict[str, Any]]:
        """Return tracked state for a named app."""
        key = self._app_key(app_name)
        record = self._app_states.get(user_id, {}).get(key)
        if record is None:
            return None
        return {
            "app_name": record.app_name,
            "pid": record.pid,
            "status": record.status,
            "launched_at": record.launched_at,
            "last_checked_at": record.last_checked_at,
            "window_title": record.window_title,
            "focused": record.focused,
            "ready": record.ready,
            "ready_checks": record.ready_checks,
            "last_reason": record.last_reason,
            "metadata": dict(record.metadata),
        }

    async def _run_ready_check(
        self,
        ready_check: Callable[..., Any],
        **kwargs: Any,
    ) -> tuple[bool, str]:
        try:
            if inspect.iscoroutinefunction(ready_check):
                result = await ready_check(**kwargs)
            else:
                result = await asyncio.to_thread(functools.partial(ready_check, **kwargs))
        except Exception as exc:
            return False, str(exc)

        if isinstance(result, tuple) and len(result) >= 2:
            return bool(result[0]), str(result[1] or "")
        if isinstance(result, dict):
            return bool(result.get("ready")), str(result.get("reason") or "")
        return bool(result), ""

    async def wait_for_app_ready(
        self,
        user_id: str,
        app_name: str,
        *,
        pid: int = 0,
        timeout_s: float = 20.0,
        poll_interval_s: float = 0.35,
        require_focus: bool = True,
        stable_count_required: int = 1,
        ready_check: Optional[Callable[..., Any]] = None,
        record_launch: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Poll live window state until an app is focused and considered ready."""
        app_label = str(app_name or "").strip()
        if not app_label:
            return {
                "ready": False,
                "app_name": "",
                "pid": 0,
                "status": "invalid",
                "reason": "App name is required.",
            }

        stable_count_required = max(1, stable_count_required)
        process_manager = self._get_process_manager()

        if record_launch:
            self.record_app_launch(
                user_id=user_id,
                app_name=app_label,
                pid=pid,
                status="launching",
                reason=f"Waiting for {app_label} to become ready.",
                metadata=metadata,
            )

        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(1.0, timeout_s)
        stable_ready_checks = 0
        last_reason = f"Waiting for {app_label} window to appear."
        resolved_pid = pid if isinstance(pid, int) and pid > 0 else 0

        while loop.time() < deadline:
            identifier: Any = resolved_pid if resolved_pid > 0 else app_label
            window = await asyncio.to_thread(process_manager.find_window, identifier)
            if window is None and resolved_pid <= 0:
                window = await asyncio.to_thread(process_manager.find_window, app_label)

            if window is None:
                stable_ready_checks = 0
                last_reason = f"Window not found for '{app_label}'."
                if record_launch:
                    self.update_app_state(
                        user_id=user_id,
                        app_name=app_label,
                        status="launching",
                        focused=False,
                        ready=False,
                        ready_checks=stable_ready_checks,
                        reason=last_reason,
                    )
                await asyncio.sleep(poll_interval_s)
                continue

            if isinstance(window.pid, int) and window.pid > 0:
                resolved_pid = window.pid

            focused_window = (
                await asyncio.to_thread(process_manager.get_focused_window)
                if require_focus else None
            )
            focus_ok = (
                not require_focus
                or (
                    focused_window is not None
                    and focused_window.window_id == window.window_id
                )
            )

            if require_focus and not focus_ok:
                focus_identifier: Any = resolved_pid if resolved_pid > 0 else app_label
                focus_ok = await asyncio.to_thread(process_manager.bring_to_focus, focus_identifier)
                if focus_ok:
                    focused_window = await asyncio.to_thread(process_manager.get_focused_window)
                    focus_ok = (
                        focused_window is not None
                        and focused_window.window_id == window.window_id
                    )

            probe_ok = True
            probe_reason = "Window detected."
            if ready_check is not None:
                probe_ok, probe_reason = await self._run_ready_check(
                    ready_check,
                    app_name=app_label,
                    pid=resolved_pid,
                    window=window,
                    focused_window=focused_window,
                    focus_ok=focus_ok,
                    ready_checks=stable_ready_checks,
                    metadata=metadata or {},
                )
                if probe_reason:
                    last_reason = probe_reason
            elif focus_ok:
                last_reason = "Window exists and is focused."

            ready_now = bool(window) and focus_ok and probe_ok
            if ready_now:
                stable_ready_checks += 1
            else:
                stable_ready_checks = 0
                if not focus_ok:
                    last_reason = f"{app_label} window is not focused yet."
                elif not probe_ok and not last_reason:
                    last_reason = f"{app_label} is still loading."

            current_status = "ready" if ready_now and stable_ready_checks >= stable_count_required else (
                "focused" if focus_ok else "window_found"
            )
            if record_launch:
                self.update_app_state(
                    user_id=user_id,
                    app_name=app_label,
                    pid=resolved_pid,
                    status=current_status,
                    window_title=window.title,
                    focused=focus_ok,
                    ready=ready_now and stable_ready_checks >= stable_count_required,
                    ready_checks=stable_ready_checks,
                    reason=last_reason,
                    metadata=metadata,
                )

            if ready_now and stable_ready_checks >= stable_count_required:
                return {
                    "ready": True,
                    "app_name": app_label,
                    "pid": resolved_pid,
                    "status": "ready",
                    "window_title": window.title,
                    "focused": True,
                    "ready_checks": stable_ready_checks,
                    "reason": last_reason or f"{app_label} is ready.",
                }

            await asyncio.sleep(poll_interval_s)

        timeout_reason = last_reason or f"Timed out waiting for {app_label}."
        if record_launch:
            self.update_app_state(
                user_id=user_id,
                app_name=app_label,
                pid=resolved_pid,
                status="timeout",
                focused=False,
                ready=False,
                ready_checks=stable_ready_checks,
                reason=timeout_reason,
                metadata=metadata,
            )
        return {
            "ready": False,
            "app_name": app_label,
            "pid": resolved_pid,
            "status": "timeout",
            "window_title": "",
            "focused": False,
            "ready_checks": stable_ready_checks,
            "reason": timeout_reason,
        }

    def mark_process_exited(self, user_id: str, pid: int) -> None:
        """Mark a tracked process as exited."""
        procs = self._active_processes.get(user_id, {})
        for key, proc in procs.items():
            if proc.pid == pid:
                proc.status = "exited"
                break

    # ── Cleanup ──────────────────────────────────────────────────────────

    def cleanup_user(self, user_id: str) -> None:
        """Remove all session data for a user."""
        self._recent_outputs.pop(user_id, None)
        self._active_processes.pop(user_id, None)
        self._app_states.pop(user_id, None)
        logger.info("Cleaned up tool context for user=%s", user_id)


# ── Singleton ────────────────────────────────────────────────────────────────

_tool_context_service: Optional[ToolContextService] = None


def get_tool_context_service() -> ToolContextService:
    global _tool_context_service
    if _tool_context_service is None:
        _tool_context_service = ToolContextService()
    return _tool_context_service
