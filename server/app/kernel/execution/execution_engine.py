# app/kernel/execution_engine.py
"""
UNIFIED Execution Engine

Single engine for BOTH server and client tasks.
- Desktop: Executes client tasks DIRECTLY (no emit, no separate loop)
- Production: Emits client tasks via WebSocket

ONE orchestrator, ONE state — no more split-brain.

Event-based completion signaling for proper async waiting
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Set
from datetime import datetime
import contextlib
import uuid

from app.kernel.execution.orchestrator import get_orchestrator
from app.kernel.execution.approval_coordinator import get_approval_coordinator
from app.kernel.execution.execution_models import TaskRecord, TaskOutput
from app.kernel.execution.binding_resolver import get_binding_resolver
from app.kernel.execution.execution_watcher import watched_execute
from app.kernel.execution.failure_classifier import classify_failure, FailureCategory, ToolError
from app.kernel.execution.job_coordinator import get_job_coordinator, JobStatus
from app.kernel.execution.replanner import (
    validate_diff, apply_diff, unblock_dependents,
    build_replan_prompt, parse_replan_response,
    DiffValidationError, MAX_REPLANS_PER_JOB, MAX_REPLANS_PER_TASK,
)
from app.kernel.execution.resource_lock import get_resource_lock_registry, MultiLockContext
from app.kernel.execution.cancellation import CancellationContext
from app.kernel.contracts.models import KernelEvent
from app.kernel.eventing.event_bus import emit_kernel_event
from app.socket.log_stream import emit_spark_log
from app.agent.runtime.tool_context_service import get_tool_context_service

logger = logging.getLogger(__name__)


async def _emit_tool_detail(user_id: str, event_type: str, task_id: str, tool_name: str, job_id: str = "", **kwargs) -> None:
    """Emit a detailed tool event for live logs."""
    try:
        await emit_spark_log(user_id, event_type, task_id=task_id, tool_name=tool_name, job_id=job_id, payload=kwargs)
    except Exception:
        pass


def _build_start_message(tool_name: str, resolved_inputs: Dict[str, Any]) -> str:
    """Build a human-readable action description when a tool starts."""
    t = tool_name.lower()
    try:
        if t == "current_location":
            return "Getting current location"
        if t == "weather_current":
            city = resolved_inputs.get("city", "")
            return f"Fetching weather for {city}" if city else "Fetching current weather"
        if t == "weather_forecast":
            city = resolved_inputs.get("city", "")
            return f"Loading forecast for {city}" if city else "Loading weather forecast"
        if t == "web_research":
            query = str(resolved_inputs.get("query", ""))[:60]
            intent = resolved_inputs.get("intent", "research")
            if intent in ("hotel_search", "product_search", "restaurant_search", "local_service"):
                return f"Searching: {query}" if query else "Searching the web"
            return f"Researching: {query}" if query else "Researching"
        if t == "web_search":
            query = str(resolved_inputs.get("query", ""))[:60]
            return f"Searching: {query}" if query else "Searching the web"
        if t == "web_scrape":
            url = str(resolved_inputs.get("url", resolved_inputs.get("base_links", "")))[:60]
            return f"Scraping: {url}" if url else "Scraping web pages"
        if t == "ai_summarize":
            return "Summarizing content"
        if t == "content_generate":
            fmt = resolved_inputs.get("format", "")
            return f"Generating {fmt} content" if fmt else "Generating content"
        if t == "shell_execute":
            cmd = str(resolved_inputs.get("command", ""))[:60]
            return f"Running: {cmd}" if cmd else "Running shell command"
        if t == "shell_agent":
            goal = str(resolved_inputs.get("goal", resolved_inputs.get("task", "")))[:60]
            return f"Working on: {goal}" if goal else "Running shell agent"
        if t == "email_list":
            return "Fetching inbox"
        if t == "email_send":
            to = resolved_inputs.get("to", "")
            return f"Sending email to {to}" if to else "Sending email"
        if t == "email_read":
            return "Reading email"
        if t == "battery_status":
            return "Checking battery"
        if t == "screenshot_capture":
            return "Capturing screenshot"
        if t == "folder_organize":
            path = str(resolved_inputs.get("path", ""))[:40]
            return f"Organizing: {path}" if path else "Organizing folder"
        if t in ("app_open", "file_open"):
            target = resolved_inputs.get("target", resolved_inputs.get("path", ""))
            return f"Opening {target}" if target else "Opening"
        if t == "sound_control":
            return "Adjusting sound"
    except Exception:
        pass
    return f"Running {tool_name.replace('_', ' ')}"


def _build_result_summary(tool_name: str, data: Dict[str, Any]) -> str:
    """Build a human-readable one-liner from tool output for live logs."""
    if not data:
        return ""
    t = tool_name.lower()
    try:
        if t == "web_research":
            rt = data.get("result_type", "")
            if rt == "entities":
                entities = data.get("entities", [])
                count = len(entities)
                if count and isinstance(entities[0], dict):
                    names = [e.get("name", "") for e in entities[:3] if e.get("name")]
                    preview = ", ".join(names)
                    if count > 3:
                        preview += f" +{count - 3} more"
                    return f"Found {count} results: {preview}"
                return f"Found {count} results"
            if rt == "snippets":
                snippets = data.get("snippets", [])
                if snippets and isinstance(snippets[0], dict):
                    return snippets[0].get("snippet", "")[:120]
                return f"Found {len(snippets)} snippets"
            if rt == "scraped_content":
                pages = data.get("scraped_content", [])
                return f"Gathered content from {len(pages)} pages"
        if t == "ai_summarize":
            summary = data.get("summary", "")
            if summary:
                return summary[:150]
        if t == "content_generate":
            fp = data.get("file_path", "")
            lines = data.get("line_count", 0)
            if fp:
                from pathlib import PurePosixPath, PureWindowsPath
                name = PureWindowsPath(fp).name if "\\" in fp else PurePosixPath(fp).name
                return f"Created {name} ({lines} lines)" if lines else f"Created {name}"
        if t == "file_create":
            fp = data.get("file_path", "")
            if fp:
                from pathlib import PurePosixPath, PureWindowsPath
                name = PureWindowsPath(fp).name if "\\" in fp else PurePosixPath(fp).name
                size = data.get("size_bytes", 0)
                if size and size > 1024:
                    return f"Created {name} ({size // 1024}KB)"
                return f"Created {name}"
        if t == "shell_execute":
            stdout = str(data.get("stdout", "")).strip()
            exit_code = data.get("exit_code", 0)
            if stdout:
                return stdout[:120]
            return f"Exit code {exit_code}"
        if t == "shell_agent":
            answer = str(data.get("final_answer", "")).strip()
            if answer:
                return answer[:150]
            steps = data.get("step_count", 0)
            return f"Completed in {steps} steps"
        if t == "weather_current":
            desc = data.get("description", "")
            temp = data.get("temperature_c")
            city = data.get("city", "")
            if desc and temp is not None:
                return f"{city}: {desc}, {temp}°C" if city else f"{desc}, {temp}°C"
        if t == "weather_forecast":
            forecast = data.get("forecast", [])
            if forecast and isinstance(forecast[0], dict):
                return f"{len(forecast)}-day forecast loaded"
        if t == "email_list":
            emails = data.get("emails", [])
            total = data.get("total_returned", len(emails))
            if emails and isinstance(emails[0], dict):
                subjects = [e.get("subject", "") for e in emails[:2] if e.get("subject")]
                preview = "; ".join(subjects)
                return f"{total} emails — {preview}" if preview else f"{total} emails"
            return f"{total} emails"
        if t == "email_send":
            to = data.get("to", "")
            subj = data.get("subject", "")
            return f"Sent to {to}: {subj}" if to else "Email sent"
        if t == "email_read":
            subj = data.get("subject", "")
            frm = data.get("from", "")
            return f"From {frm}: {subj}" if frm else subj or "Email loaded"
        if t == "folder_organize":
            moved = data.get("moved_count", data.get("files_moved", 0))
            return f"Organized {moved} files" if moved else "Folder organized"
        if t == "screenshot_capture":
            fp = data.get("file_path", "")
            return f"Screenshot saved" if fp else "Screenshot captured"
        if t == "battery_status":
            pct = data.get("percent")
            charging = data.get("is_charging")
            if pct is not None:
                status = "charging" if charging else "on battery"
                return f"{pct}% — {status}"
        if t in ("app_open", "file_open"):
            return data.get("message", "") or "Opened"
        if t == "current_location":
            city = data.get("city", "")
            region = data.get("region", "")
            lat = data.get("latitude")
            lon = data.get("longitude")
            if city:
                return f"{city}, {region}" if region else city
            if lat is not None and lon is not None:
                return f"Location: {lat:.4f}, {lon:.4f}"
    except Exception:
        pass
    return ""


async def _emit_progress_event(user_id: str, summary: dict) -> None:
    try:
        from app.socket.utils import socket_emit
        await socket_emit("task:progress", {"user_id": user_id, "summary": summary}, user_id=user_id)
    except Exception:
        pass


async def _emit_summary_event(user_id: str, summary: dict) -> None:
    try:
        from app.socket.utils import socket_emit
        await socket_emit("task:summary", {"user_id": user_id, "summary": summary}, user_id=user_id)
    except Exception:
        pass


class ExecutionEngine:
    """
    UNIFIED execution engine — handles ALL tasks in ONE loop.
    
    Desktop mode:
        - Server tasks → server_tool_executor
        - Client tasks → client_tool_executor (direct, same process)
    
    Production mode:
        - Server tasks → server_tool_executor
        - Client tasks → emit via WebSocket, wait for ack
    """
    
    def __init__(self):
        self.orchestrator = get_orchestrator()
        self.binding_resolver = get_binding_resolver()
        
        # Track running engines per user/job: key = "user_id:job_id"
        self.running_engines: Dict[str, asyncio.Task] = {}

        # Completion events for awaiting execution: key = "user_id:job_id"
        self.completion_events: Dict[str, asyncio.Event] = {}

        # Track which failed task_ids have already been sent to the replanner
        # to avoid double-replanning. Key = "user_id:job_id", value = set of task_ids
        self._replan_attempted: Dict[str, Set[str]] = {}

        # Active CancellationContexts per job: key = "user_id:job_id"
        self._cancellation_contexts: Dict[str, CancellationContext] = {}

        # Tool executors (injected at startup)
        self.server_tool_executor = None
        self.client_tool_executor = None    # NEW: For desktop direct execution
        self.socket_handler = None          # For production WebSocket emit
        
        # Environment
        from app.config import settings
        self.environment = settings.environment
        
        logger.info(f"Unified Execution Engine initialized (env={self.environment})")
    
    def set_server_executor(self, executor):
        """Inject server tool executor"""
        self.server_tool_executor = executor
    
    def set_client_executor(self, executor):
        """NEW: Inject client tool executor (for desktop direct execution)"""
        self.client_tool_executor = executor
        logger.info("Client tool executor injected (desktop direct execution)")
    
    def set_client_emitter(self, emitter):
        """Set client task emitter (for backward compat / production)"""
        self.socket_handler = emitter
    
    # Keep old name working
    @property
    def client_task_emitter(self):
        return self.socket_handler
    
    async def start_execution(self, user_id: str, job_id: str = "default") -> asyncio.Task:
        """
        Start execution engine for a user/job (non-blocking).
        Creates a background task that runs the execution loop.
        """
        engine_key = f"{user_id}:{job_id}"

        # Check if already running for this user/job
        if engine_key in self.running_engines:
            existing = self.running_engines[engine_key]
            if not existing.done():
                logger.info(f" Execution already running for {engine_key}")
                return existing

        # Create completion event for a fresh run.
        self.completion_events[engine_key] = asyncio.Event()
        self._replan_attempted[engine_key] = set()
        self._cancellation_contexts[engine_key] = CancellationContext()

        # Start new background task
        task = asyncio.create_task(
            self._execution_loop(user_id, job_id)
        )
        self.running_engines[engine_key] = task

        # Update job coordinator status
        get_job_coordinator().update_status(user_id, job_id, JobStatus.RUNNING)

        logger.info(f"Started execution engine for: {engine_key}")
        return task
    
    async def wait_for_completion(self, user_id: str, timeout: float = 30, job_id: str = "default") -> bool:
        """Wait for execution to complete with timeout"""
        engine_key = f"{user_id}:{job_id}"
        if engine_key not in self.completion_events:
            logger.warning(f" No execution running for {engine_key}")
            return False

        try:
            logger.info(f"Waiting for execution to complete (timeout: {timeout}s)...")
            await asyncio.wait_for(
                self.completion_events[engine_key].wait(),
                timeout=timeout
            )
            logger.info(f"Execution completed for {engine_key}")
            return True

        except asyncio.TimeoutError:
            logger.warning(f"⏰ Timeout waiting for {engine_key} execution after {timeout}s")
            return False

    async def get_execution_speech_snapshot(
        self,
        user_id: str,
        max_tasks: int = 12,
    ) -> Dict[str, Any]:
        """Expose orchestrator snapshot for post-execution speech synthesis."""
        return await self.orchestrator.build_execution_speech_snapshot(
            user_id=user_id,
            max_tasks=max_tasks,
        )
    
    async def _execution_loop(self, user_id: str, job_id: str = "default") -> None:
        """
        Main execution loop for a user/job.
        Runs continuously until all tasks are done or timeout.
        Integrates failure classification and patch-based replanning.
        """
        engine_key = f"{user_id}:{job_id}"

        logger.info(f"\n{'='*70}")
        logger.info(f"EXECUTION LOOP STARTED: {engine_key}")
        logger.info(f"{'='*70}\n")

        await emit_spark_log(user_id, "execution_started", payload={"message": f"Execution started (job={job_id})", "job_id": job_id})

        iteration = 0
        max_iterations = 100  # Safety limit
        no_work_count = 0
        max_idle = 3

        try:
            while iteration < max_iterations:
                iteration += 1

                # Check cancellation
                cancel_ctx = self._cancellation_contexts.get(engine_key)
                if cancel_ctx and cancel_ctx.is_cancelled:
                    logger.info(f"Job {engine_key} was cancelled — exiting loop")
                    break

                # FAST EXIT: No tasks registered = nothing to do
                state = self.orchestrator.states.get(engine_key) or self.orchestrator.get_state(user_id)
                if not state or len(state.tasks) == 0:
                    logger.info(f"No tasks registered for {engine_key} — exiting immediately")
                    break

                # Check if ALL tasks are terminal (completed/failed/blocked-with-no-replan)
                pending = state.get_tasks_by_status("pending")
                running = state.get_tasks_by_status("running")
                emitted = state.get_tasks_by_status("emitted")
                waiting = state.get_tasks_by_status("waiting")
                blocked = state.get_tasks_by_status("blocked")

                if not pending and not running and not emitted and not waiting and not blocked:
                    logger.info(f"All tasks finished for {engine_key} — exiting")
                    break

                # If only blocked tasks remain (no pending/running/emitted/waiting),
                # replanning has been exhausted — nothing more can run.
                if blocked and not pending and not running and not emitted and not waiting:
                    logger.info(f"Only blocked tasks remain for {engine_key} — marking as failed")
                    for bt in blocked:
                        bt.status = "failed"
                        bt.error = bt.error or "Blocked: replanning could not resolve upstream failure"
                    break

                # Reap stuck emitted/waiting tasks that exceeded their timeout.
                await self._reap_stuck_tasks(user_id, emitted, waiting)

                logger.info(f"\n{'─'*70}")
                logger.info(f"Iteration {iteration} - {engine_key}")
                logger.info(f"{'─'*70}")

                # 1. Get executable batch
                batch = await self.orchestrator.get_executable_batch(user_id, job_id=job_id)

                logger.info(f"🔍 Found {len(batch.server_tasks)} server tasks, {len(batch.client_tasks)} client tasks")

                has_work = bool(batch.server_tasks or batch.client_tasks)

                if not has_work:
                    waiting_now = state.get_tasks_by_status("waiting")
                    if waiting_now:
                        logger.info("⏳ Waiting for %d approval task(s)...", len(waiting_now))
                        await asyncio.sleep(0.2)
                        continue

                    no_work_count += 1
                    logger.info(f" No runnable tasks (idle count: {no_work_count}/{max_idle})")

                    if no_work_count >= max_idle:
                        logger.info("No more work — execution complete!")
                        break

                    await asyncio.sleep(0.2)
                    continue

                # Reset idle counter
                no_work_count = 0

                logger.info(f"Batch: {len(batch.server_tasks)} server, {len(batch.client_tasks)} client")

                # 2. Execute server + client tasks in PARALLEL
                parallel_work = []

                if batch.server_tasks:
                    logger.info(f"\nExecuting {len(batch.server_tasks)} server tasks...")
                    parallel_work.append(self._execute_server_batch(user_id, batch.server_tasks, job_id=job_id))

                if batch.client_tasks:
                    logger.info(f"\n Handling {len(batch.client_tasks)} client tasks...")
                    parallel_work.append(self._handle_client_batch(user_id, batch.client_tasks, job_id=job_id))

                if parallel_work:
                    results = await asyncio.gather(*parallel_work, return_exceptions=True)
                    for i, result in enumerate(results):
                        if isinstance(result, Exception):
                            logger.error(f"Parallel work item {i} failed: {result}")

                # 3. After batch execution — check for RECOVERABLE failures and replan
                await self._check_and_replan(user_id, job_id, state)

                # Emit lightweight progress snapshot for UI/agent listeners
                progress = await self.orchestrator.get_execution_summary(user_id)
                progress["job_id"] = job_id
                await _emit_progress_event(user_id, progress)

                # Small delay before next iteration
                await asyncio.sleep(0.1)

            if iteration >= max_iterations:
                logger.warning(f" Max iterations reached for {engine_key}")

        except Exception as e:
            logger.error(f"Execution loop error for {engine_key}: {e}", exc_info=True)

        finally:
            # Cleanup
            if engine_key in self.running_engines:
                del self.running_engines[engine_key]
            self._replan_attempted.pop(engine_key, None)
            self._cancellation_contexts.pop(engine_key, None)

            await self._print_final_summary(user_id, job_id=job_id)

            # Signal completion event
            if engine_key in self.completion_events:
                self.completion_events[engine_key].set()
                logger.info(f"Completion event signaled for {engine_key}")

            # Update job coordinator
            summary = await self.orchestrator.get_execution_summary(user_id)
            if summary.get("failed", 0) > 0:
                get_job_coordinator().update_status(user_id, job_id, JobStatus.FAILED)
            else:
                get_job_coordinator().update_status(user_id, job_id, JobStatus.COMPLETED)

            logger.info(f"\n{'='*70}")
            logger.info(f"EXECUTION LOOP ENDED: {engine_key}")
            logger.info(f"{'='*70}\n")
    
    # ==================== REPLANNER INTEGRATION ====================

    async def _check_and_replan(self, user_id: str, job_id: str, state) -> None:
        """
        After a batch executes, scan for newly failed tasks.
        For RECOVERABLE failures, invoke the LLM replanner.
        """
        engine_key = f"{user_id}:{job_id}"
        attempted = self._replan_attempted.get(engine_key, set())

        failed_tasks = state.get_tasks_by_status("failed")
        for failed_task in failed_tasks:
            if failed_task.task_id in attempted:
                continue  # Already attempted replan for this task

            # Classify the failure
            category = classify_failure(failed_task.tool, Exception(failed_task.error or "Unknown"))

            if category == FailureCategory.TERMINAL:
                logger.info(f"[Replan] Task {failed_task.task_id} is TERMINAL — no replan")
                attempted.add(failed_task.task_id)
                continue

            if category == FailureCategory.TRANSIENT:
                # Transient failures are already retried by watched_execute.
                # If we're here, retries were exhausted — treat as recoverable.
                logger.info(f"[Replan] Task {failed_task.task_id} was TRANSIENT but retries exhausted — attempting replan")

            # RECOVERABLE (or exhausted TRANSIENT) — attempt replan
            attempted.add(failed_task.task_id)
            await self._attempt_replan(user_id, job_id, failed_task, state)

    async def _attempt_replan(self, user_id: str, job_id: str, failed_task, state) -> None:
        """Invoke the LLM replanner for a single recoverable failure."""
        engine_key = f"{user_id}:{job_id}"
        coordinator = get_job_coordinator()
        meta = coordinator.get_job(user_id, job_id)

        # Budget check — per-job
        if meta and meta.replan_count >= MAX_REPLANS_PER_JOB:
            logger.warning(f"[Replan] Job {job_id} exceeded MAX_REPLANS_PER_JOB ({MAX_REPLANS_PER_JOB})")
            await emit_spark_log(user_id, "job:replan_exhausted", payload={
                "job_id": job_id, "reason": "Job replan budget exhausted",
            })
            return

        # Budget check — per-task (using task_id as lineage_id)
        lineage_id = failed_task.task_id
        if meta:
            task_count = meta.task_replan_counts.get(lineage_id, 0)
            if task_count >= MAX_REPLANS_PER_TASK:
                logger.warning(f"[Replan] Task {lineage_id} exceeded MAX_REPLANS_PER_TASK ({MAX_REPLANS_PER_TASK})")
                return

        logger.info(f"[Replan] Invoking replanner for task {failed_task.task_id} in job {job_id}")

        # Emit job:replanning event
        coordinator.update_status(user_id, job_id, JobStatus.REPLANNING)
        try:
            from app.socket.utils import socket_emit
            await socket_emit("job:replanning", {
                "user_id": user_id, "job_id": job_id,
                "task_id": failed_task.task_id,
                "error": failed_task.error,
            }, user_id=user_id)
        except Exception:
            pass

        # Build replanner prompt
        try:
            available_tools = list(self.orchestrator.tool_registry.get_all_tools().keys())
        except Exception:
            available_tools = []

        # Gather cross-job context
        other_jobs = []
        for j in coordinator.get_active_jobs(user_id):
            if j.job_id != job_id:
                other_jobs.append({"job_id": j.job_id, "goal": j.goal[:100], "status": j.status.value})

        budget_remaining = {
            "replans_left": MAX_REPLANS_PER_JOB - (meta.replan_count if meta else 0),
            "task_replans_left": MAX_REPLANS_PER_TASK - (meta.task_replan_counts.get(lineage_id, 0) if meta else 0),
        }

        # Active resource locks for context
        active_locks: List[str] = []
        registry = get_resource_lock_registry()
        user_locks = registry._locks.get(user_id, {})
        for res_key, lock in user_locks.items():
            if lock.locked():
                active_locks.append(res_key)

        compact_fn = self.orchestrator._compact_summary_value
        original_query = meta.goal if meta else ""

        messages = build_replan_prompt(
            original_query=original_query,
            failed_task=failed_task,
            state=state,
            available_tools=available_tools,
            budget_remaining=budget_remaining,
            compact_fn=compact_fn,
            active_locks=active_locks,
            other_jobs=other_jobs,
        )

        # Call LLM
        try:
            from app.ai.providers.router import routed_chat
            raw_response, _meta = await routed_chat(
                "lightweight", messages=messages, temperature=0.0, max_tokens=800,
            )
        except Exception as exc:
            logger.error(f"[Replan] LLM call failed: {exc}")
            coordinator.update_status(user_id, job_id, JobStatus.RUNNING)
            return

        # Track tokens used (approximate)
        tokens_used = len(raw_response or "") // 4  # rough estimate
        if meta:
            coordinator.increment_replan(user_id, job_id, tokens_used)
            coordinator.increment_task_replan(user_id, job_id, lineage_id)

        # Parse response
        diff_ops = parse_replan_response(raw_response or "")
        if not diff_ops:
            logger.info(f"[Replan] Replanner returned empty diff — no recovery possible")
            coordinator.update_status(user_id, job_id, JobStatus.RUNNING)
            return

        # Validate diff
        try:
            validate_diff(state, diff_ops)
        except DiffValidationError as exc:
            logger.error(f"[Replan] Diff validation failed: {exc}")
            coordinator.update_status(user_id, job_id, JobStatus.RUNNING)
            return

        # Check for non-idempotent tasks in the diff that need approval
        needs_approval = self._diff_needs_approval(diff_ops)
        if needs_approval:
            logger.info(f"[Replan] Diff introduces non-idempotent tasks: {needs_approval}")
            # For now, log and proceed. Full approval integration is a follow-up.
            # TODO: wire through ApprovalCoordinator for non-idempotent replan tasks

        # Apply diff transactionally
        apply_diff(state, diff_ops)
        logger.info(f"[Replan] Applied {len(diff_ops)} diff ops to job {job_id}")

        # Unblock dependents that can now proceed
        unblocked = unblock_dependents(state, failed_task.task_id)
        if unblocked:
            logger.info(f"[Replan] Unblocked tasks: {unblocked}")

        # Resume job
        coordinator.update_status(user_id, job_id, JobStatus.RUNNING)

        try:
            from app.socket.utils import socket_emit
            await socket_emit("job:resumed", {
                "user_id": user_id, "job_id": job_id,
                "diff_ops": len(diff_ops), "unblocked": unblocked,
            }, user_id=user_id)
        except Exception:
            pass

    def _diff_needs_approval(self, diff_ops: List[Dict[str, Any]]) -> List[str]:
        """Check if any tasks introduced by the diff are non-idempotent."""
        NON_IDEMPOTENT_TOOLS = {
            "email_send", "message_send", "file_delete", "folder_delete",
            "send_notification", "calendar_create",
        }
        flagged = []
        for op in diff_ops:
            if op.get("op") == "insert_before":
                for t in op.get("tasks", []):
                    if t.get("tool") in NON_IDEMPOTENT_TOOLS:
                        flagged.append(t.get("tool"))
            elif op.get("op") == "replace":
                w = op.get("with", {})
                if w.get("tool") in NON_IDEMPOTENT_TOOLS:
                    flagged.append(w.get("tool"))
        return flagged

    # ==================== RESOURCE LOCK HELPERS ====================

    # Maps tool_name -> resource key(s) the tool requires.
    # Tools not listed here don't acquire any resource lock.
    _TOOL_RESOURCE_MAP: Dict[str, str] = {
        "shell_execute": "shell",
        "shell_agent": "shell",
        "terminal_command": "shell",
        "browser_open": "browser",
        "browser_navigate": "browser",
        "chrome_action": "browser",
        "tts_speak": "tts",
        "text_to_speech": "tts",
    }

    def _get_tool_resources(self, tool_name: str) -> List[str]:
        """Get the resource keys a tool requires (empty list if none)."""
        resource = self._TOOL_RESOURCE_MAP.get(tool_name)
        return [resource] if resource else []

    # ==================== STUCK TASK REAPER ====================

    _EMITTED_TIMEOUT_S = 120.0   # 2 min — client should ack well before this
    _WAITING_TIMEOUT_S = 180.0   # 3 min — user should respond to approval

    async def _reap_stuck_tasks(
        self,
        user_id: str,
        emitted: list,
        waiting: list,
    ) -> None:
        """Fail tasks that have been in emitted/waiting state too long."""
        from datetime import datetime

        now = datetime.now()
        for task in emitted:
            if task.emitted_at and (now - task.emitted_at).total_seconds() > self._EMITTED_TIMEOUT_S:
                error = f"Client did not acknowledge within {self._EMITTED_TIMEOUT_S:.0f}s"
                logger.warning("Reaping stuck emitted task %s: %s", task.task_id, error)
                await self.orchestrator.mark_task_failed(user_id, task.task_id, error)

        for task in waiting:
            started = task.started_at or task.created_at
            if started and (now - started).total_seconds() > self._WAITING_TIMEOUT_S:
                error = f"Approval not received within {self._WAITING_TIMEOUT_S:.0f}s"
                logger.warning("Reaping stuck waiting task %s: %s", task.task_id, error)
                await self.orchestrator.mark_task_failed(user_id, task.task_id, error)

    # ==================== SERVER TASK EXECUTION ====================
    
    async def _execute_server_batch(self, user_id: str, tasks: list[TaskRecord], job_id: str = "default") -> None:
        """Execute multiple server tasks in parallel"""
        if not self.server_tool_executor:
            logger.error("No server tool executor configured!")
            return
        
        results = await asyncio.gather(
            *[self._execute_single_server_task(user_id, task, job_id=job_id) for task in tasks],
            return_exceptions=True
        )
        
        success_count = sum(1 for r in results if r is True)
        logger.info(f"Completed {success_count}/{len(tasks)} server tasks")
    
    async def _execute_single_server_task(self, user_id: str, task: TaskRecord, job_id: str = "default") -> bool:
        """Execute a single server task"""
        try:
            await self.orchestrator.mark_task_running(user_id, task.task_id, job_id=job_id)

            logger.info(f"  Executing: {task.task_id} ({task.tool})")
            await emit_spark_log(user_id, "task_running", task_id=task.task_id, tool_name=task.tool, status="running", job_id=job_id, payload={"message": f"Executing {task.tool}"})

            if task.lifecycle_messages and task.lifecycle_messages.on_start:
                logger.info(f"     {task.lifecycle_messages.on_start}")

            # Optional approval gate tasks are resolved via notification response.
            if not await self._handle_approval_gate(user_id, task):
                return False

            if not self.server_tool_executor:
                raise RuntimeError("Server tool executor not configured")

            # RESOLVE INPUT BINDINGS — find the correct job state for this task
            state = self.orchestrator._find_state_for_task(user_id, task.task_id, job_id=job_id)
            if not state:
                raise RuntimeError(f"No execution state for task {task.task_id}")

            can_resolve, error = self.binding_resolver.validate_bindings(task, state)
            if not can_resolve:
                raise ValueError(f"Cannot resolve bindings: {error}")

            resolved_inputs = self.binding_resolver.resolve_inputs(task, state)
            resolved_inputs["_user_id"] = user_id
            resolved_inputs["user_id"] = user_id
            resolved_inputs["_task_id"] = task.task_id
            resolved_inputs["_execution_id"] = state.execution_id
            resolved_inputs["execution_id"] = state.execution_id
            task.resolved_inputs = resolved_inputs

            logger.info(f"     📋 Resolved inputs: {list(resolved_inputs.keys())}")
            start_msg = _build_start_message(task.tool, resolved_inputs)
            await _emit_tool_detail(user_id, "tool_step", task.task_id, task.tool, job_id=job_id, message=start_msg)

            # Dynamic approval for shell_execute commands that aren't whitelisted
            if task.tool == "shell_execute" and not (task.control and task.control.requires_approval):
                from app.services.shell.sandbox import SecuritySandbox
                from app.services.shell.user_permissions import get_user_permission_store
                _sandbox = SecuritySandbox()
                _cmd = resolved_inputs.get("command", "")
                _allowed, _reason = _sandbox.validate(_cmd)
                if _reason == "requires_approval" and not get_user_permission_store().is_permitted(user_id, _cmd):
                    from app.kernel.execution.execution_models import TaskControl
                    task.task.control = TaskControl(
                        requires_approval=True,
                        approval_question=f"Allow command: {_cmd}?",
                    )
                    if not await self._handle_approval_gate(user_id, task):
                        return False
                    # User approved — grant persistent permission
                    get_user_permission_store().grant(user_id, _cmd)
            
            # Get timeout
            timeout = None
            if task.control and task.control.timeout_ms:
                timeout = task.control.timeout_ms / 1000
            
            # Execute via watcher (auto-retry on retryable failures)
            async def _server_exec_fn(_task: TaskRecord, _inputs: dict) -> TaskOutput:
                _task.resolved_inputs = _inputs
                if timeout:
                    return await asyncio.wait_for(
                        self.server_tool_executor.execute(_task),
                        timeout=timeout
                    )
                return await self.server_tool_executor.execute(_task)

            async def _on_server_retry(_uid: str, attempt: int, msg: str) -> None:
                await _emit_progress_event(_uid, {"retry": True, "task_id": task.task_id, "attempt": attempt, "message": msg})
                await _emit_tool_detail(_uid, "tool_retry", task.task_id, task.tool, job_id=job_id, attempt=attempt, message=msg)

            # Acquire resource lock if needed (prevents cross-job contention)
            resources = self._get_tool_resources(task.tool)
            lock_registry = get_resource_lock_registry()

            async def _run_watched():
                return await watched_execute(
                    user_id=user_id,
                    task=task,
                    resolved_inputs=resolved_inputs,
                    executor_fn=_server_exec_fn,
                    on_retry=_on_server_retry,
                    get_task_output_fn=lambda tid: self.orchestrator.get_task(user_id, tid).output if self.orchestrator.get_task(user_id, tid) else None,
                )

            if resources:
                async with MultiLockContext(lock_registry, user_id, resources):
                    watcher_result = await _run_watched()
            else:
                watcher_result = await _run_watched()

            output = watcher_result.output

            if watcher_result.recovered:
                            logger.info(f"     🔄 Watcher recovered task {task.task_id} after {watcher_result.retries_used} retries")
                            await _emit_tool_detail(user_id, "tool_recovered", task.task_id, task.tool, job_id=job_id, retries=watcher_result.retries_used, message=f"🔄 Recovered after {watcher_result.retries_used} retry(s)")

            if output.success:
                await self.orchestrator.mark_task_completed(user_id, task.task_id, output, job_id=job_id)
                result_summary = _build_result_summary(task.tool, output.data or {})
                display_msg = result_summary or f"✓ {task.tool} completed"
                await _emit_tool_detail(user_id, "tool_output", task.task_id, task.tool, job_id=job_id, success=True, data={k: str(v)[:100] for k, v in list((output.data or {}).items())[:6]}, duration_ms=task.duration_ms, message=display_msg, result_summary=result_summary)
                get_tool_context_service().record_tool_output(
                    user_id=user_id, task_id=task.task_id, tool_name=task.tool,
                    output_data=output.data, success=True,
                )
                if task.lifecycle_messages and task.lifecycle_messages.on_success:
                    logger.info(f"     {task.lifecycle_messages.on_success}")
                logger.info(f"  Completed: {task.task_id} ({task.duration_ms}ms)")
                return True
            else:
                error = output.error or f"Tool '{task.tool}' returned unsuccessful output"
                await _emit_tool_detail(user_id, "tool_output", task.task_id, task.tool, job_id=job_id, success=False, error=error[:200], message=f"✗ {task.tool} failed: {error[:100]}")
                ctx = get_tool_context_service()
                ctx.record_tool_output(
                    user_id=user_id, task_id=task.task_id, tool_name=task.tool,
                    output_data=output.data, success=False, error=error,
                )
                await self.orchestrator.mark_task_failed(user_id, task.task_id, error, job_id=job_id)
                if task.lifecycle_messages and task.lifecycle_messages.on_failure:
                    logger.info(f"     {task.lifecycle_messages.on_failure}")
                logger.error(f"  Failed: {task.task_id} - {error}")
                return False
        
        except asyncio.TimeoutError:
            error = f"Task timed out after {timeout}s" # type: ignore
            await self.orchestrator.mark_task_failed(user_id, task.task_id, error, job_id=job_id)
            if task.lifecycle_messages and task.lifecycle_messages.on_failure:
                logger.info(f"     {task.lifecycle_messages.on_failure}")
            return False
        
        except Exception as e:
            error = str(e)
            await self.orchestrator.mark_task_failed(user_id, task.task_id, error, job_id=job_id)
            if task.lifecycle_messages and task.lifecycle_messages.on_failure:
                logger.info(f"     {task.lifecycle_messages.on_failure}")
            return False
    
    # ==================== CLIENT TASK HANDLING ====================
    
    async def _handle_client_batch(self, user_id: str, tasks: list[TaskRecord], job_id: str = "default") -> None:
        """
        UNIFIED: Handle client tasks based on environment.
        
        Desktop: Execute DIRECTLY (same orchestrator, same state)
        Production: Emit via WebSocket
        """
        if self.environment == "DESKTOP":
            await self._execute_client_batch_locally(user_id, tasks, job_id=job_id)
        else:
            await self._emit_client_batch_remote(user_id, tasks, job_id=job_id)
    
    async def _execute_client_batch_locally(self, user_id: str, tasks: list[TaskRecord], job_id: str = "default") -> None:
        """
        DESKTOP MODE: Execute client tasks DIRECTLY.
        
        Dependency chains are executed sequentially so bindings resolve correctly.
        Independent tasks still run in parallel.
        """
        if not self.client_tool_executor:
            logger.error("No client tool executor configured for desktop mode!")
            for task in tasks:
                await self.orchestrator.mark_task_failed(
                    user_id, task.task_id,
                    "Client tool executor not configured",
                    job_id=job_id
                )
            return
        
        # If tasks form a dependency chain, execute sequentially
        if self._is_dependency_chain(tasks):
            success_count = 0
            for task in tasks:
                result = await self._execute_single_client_task(user_id, task, job_id=job_id)
                if result:
                    success_count += 1
                else:
                    # Cascade: fail remaining tasks in chain
                    idx = tasks.index(task)
                    for remaining in tasks[idx + 1:]:
                        await self.orchestrator.mark_task_failed(
                            user_id, remaining.task_id,
                            f"Skipped: dependency {task.task_id} failed",
                            job_id=job_id
                        )
                    break
            logger.info(f"Completed {success_count}/{len(tasks)} client tasks locally")
        else:
            results = await asyncio.gather(
                *[self._execute_single_client_task(user_id, task, job_id=job_id) for task in tasks],
                return_exceptions=True
            )
            success_count = sum(1 for r in results if r is True)
            logger.info(f"Completed {success_count}/{len(tasks)} client tasks locally")
    
    async def _execute_single_client_task(self, user_id: str, task: TaskRecord, job_id: str = "default") -> bool:
        """Execute a single client task locally (desktop mode) with watcher recovery"""
        try:
            await self.orchestrator.mark_task_running(user_id, task.task_id, job_id=job_id)

            logger.info(f"   Executing locally: {task.task_id} ({task.tool})")
            await emit_spark_log(user_id, "task_running", task_id=task.task_id, tool_name=task.tool, status="running", job_id=job_id, payload={"message": f"Executing {task.tool} locally"})

            if task.lifecycle_messages and task.lifecycle_messages.on_start:
                logger.info(f"     {task.lifecycle_messages.on_start}")

            # Optional approval gate tasks are resolved via notification response.
            if not await self._handle_approval_gate(user_id, task):
                return False

            # Resolve inputs — find the correct job state for this task
            state = self.orchestrator._find_state_for_task(user_id, task.task_id, job_id=job_id)
            if not state:
                raise RuntimeError(f"No execution state for task {task.task_id}")

            can_resolve, error = self.binding_resolver.validate_bindings(task, state)
            if not can_resolve:
                raise ValueError(f"Cannot resolve bindings: {error}")

            resolved_inputs = self.binding_resolver.resolve_inputs(task, state)
            resolved_inputs["_user_id"] = user_id
            resolved_inputs["user_id"] = user_id
            resolved_inputs["_task_id"] = task.task_id
            resolved_inputs["_execution_id"] = state.execution_id
            resolved_inputs["execution_id"] = state.execution_id
            task.resolved_inputs = resolved_inputs

            logger.info(f"     📋 Resolved inputs: {list(resolved_inputs.keys())}")
            start_msg = _build_start_message(task.tool, resolved_inputs)
            await _emit_tool_detail(user_id, "tool_step", task.task_id, task.tool, job_id=job_id, message=start_msg)
            
            # Execute via watcher (auto-retry on retryable failures)
            client_executor = self.client_tool_executor
            if client_executor is None:
                raise RuntimeError("Client tool executor not configured")

            async def _exec_fn(_task: TaskRecord, _inputs: dict) -> TaskOutput:
                return await client_executor.execute(_task, _inputs)

            async def _on_retry(_uid: str, attempt: int, msg: str) -> None:
                await _emit_progress_event(_uid, {"retry": True, "task_id": task.task_id, "attempt": attempt, "message": msg})

            # Acquire resource lock if needed (prevents cross-job contention)
            resources = self._get_tool_resources(task.tool)
            lock_registry = get_resource_lock_registry()

            async def _run_client_watched():
                return await watched_execute(
                    user_id=user_id,
                    task=task,
                    resolved_inputs=resolved_inputs,
                    executor_fn=_exec_fn,
                    on_retry=_on_retry,
                    get_task_output_fn=lambda tid: self.orchestrator.get_task(user_id, tid).output if self.orchestrator.get_task(user_id, tid) else None,
                )

            local_t0 = datetime.now()
            if resources:
                async with MultiLockContext(lock_registry, user_id, resources):
                    watcher_result = await _run_client_watched()
            else:
                watcher_result = await _run_client_watched()

            latency_ms = int((datetime.now() - local_t0).total_seconds() * 1000)
            output = watcher_result.output

            if watcher_result.recovered:
                            logger.info(f"     🔄 Watcher recovered task {task.task_id} after {watcher_result.retries_used} retries")
                            await _emit_tool_detail(user_id, "tool_recovered", task.task_id, task.tool, job_id=job_id, retries=watcher_result.retries_used, message=f"🔄 Recovered after {watcher_result.retries_used} retry(s)")

            if output.success:
                await self.orchestrator.mark_task_completed(user_id, task.task_id, output, job_id=job_id)
                result_summary = _build_result_summary(task.tool, output.data or {})
                display_msg = result_summary or f"✓ {task.tool} completed"
                await _emit_tool_detail(user_id, "tool_output", task.task_id, task.tool, job_id=job_id, success=True, data={k: str(v)[:100] for k, v in list((output.data or {}).items())[:6]}, duration_ms=latency_ms, message=display_msg, result_summary=result_summary)
                await emit_kernel_event(
                    KernelEvent(
                        event_type="tool_invoked",
                        user_id=user_id,
                        task_id=task.task_id,
                        tool_name=task.tool,
                        status="success",
                        job_id=job_id,
                        payload={"latency_ms": latency_ms, "error": None, "recovered": watcher_result.recovered, "result_summary": result_summary},
                    )
                )
                get_tool_context_service().record_tool_output(
                    user_id=user_id, task_id=task.task_id, tool_name=task.tool,
                    output_data=output.data, success=True,
                )
                if task.lifecycle_messages and task.lifecycle_messages.on_success:
                    logger.info(f"     {task.lifecycle_messages.on_success}")
                logger.info(f"  Completed locally: {task.task_id}")
                return True
            else:
                error_msg = watcher_result.watcher_message or output.error or f"Client tool '{task.tool}' failed"
                await _emit_tool_detail(user_id, "tool_output", task.task_id, task.tool, job_id=job_id, success=False, error=error_msg[:200], message=f"✗ {task.tool} failed: {error_msg[:100]}")
                await self.orchestrator.mark_task_failed(user_id, task.task_id, error_msg, job_id=job_id)
                await emit_kernel_event(
                    KernelEvent(
                        event_type="tool_failed",
                        user_id=user_id,
                        task_id=task.task_id,
                        tool_name=task.tool,
                        status="failed",
                        job_id=job_id,
                        payload={"latency_ms": latency_ms, "error": error_msg},
                    )
                )
                if task.lifecycle_messages and task.lifecycle_messages.on_failure:
                    logger.info(f"     {task.lifecycle_messages.on_failure}")
                logger.error(f"  Failed locally: {task.task_id} - {error_msg}")
                return False
        
        except Exception as e:
            error_msg = str(e)
            await self.orchestrator.mark_task_failed(user_id, task.task_id, error_msg, job_id=job_id)
            await emit_kernel_event(
                KernelEvent(
                    event_type="tool_failed",
                    user_id=user_id,
                    task_id=task.task_id,
                    tool_name=task.tool,
                    status="failed",
                    job_id=job_id,
                    payload={"error": error_msg},
                )
            )
            
            if task.lifecycle_messages and task.lifecycle_messages.on_failure:
                logger.info(f"     {task.lifecycle_messages.on_failure}")
            
            logger.error(f"  Failed locally: {task.task_id} - {error_msg}")
            return False
    async def _handle_approval_gate(self, user_id: str, task: TaskRecord) -> bool:
        """
        Handle task-level approval gate.

        Returns:
            True  -> continue normal tool execution
            False -> stop execution for this task (approval flow owns final status)
        """
        control = task.control
        if not control or not control.requires_approval:
            return True

        current = self.orchestrator.get_task(user_id, task.task_id)
        if current and current.approval_state == "approved":
            return True
        if current and current.approval_state == "requested":
            return False

        question = control.approval_question or f"Allow '{task.tool}' to run?"
        state = self.orchestrator._find_state_for_task(user_id, task.task_id)
        execution_id = state.execution_id if state else ""
        request_id = f"{task.task_id}::approval::{uuid.uuid4().hex[:8]}"
        await self.orchestrator.mark_task_waiting(user_id, task.task_id, request_id=request_id)

        if not self.socket_handler or not hasattr(self.socket_handler, "submit_approval_request"):
            await self.orchestrator.mark_task_failed(
                user_id,
                task.task_id,
                "Approval requested but no approval handler is configured",
            )
            return False

        async def _handle_response(_user_id: str, _request_id: str, approved: bool) -> None:
            if approved:
                await self.orchestrator.mark_task_approval_approved(
                    user_id,
                    task.task_id,
                    request_id=_request_id,
                )
            else:
                await self.orchestrator.mark_task_approval_denied(
                    user_id,
                    task.task_id,
                    request_id=_request_id,
                    reason="User denied approval",
                )

        try:
            submitted = await self.socket_handler.submit_approval_request(
                user_id=user_id,
                task_id=request_id,
                question=question,
                execution_id=execution_id,
                on_response_callback=_handle_response,
            )
        except Exception as exc:
            await self.orchestrator.mark_task_failed(
                user_id,
                task.task_id,
                f"Approval flow failed: {exc}",
            )
            return False

        if not submitted:
            current = self.orchestrator.get_task(user_id, task.task_id)
            if current and current.status == "waiting":
                await self.orchestrator.mark_task_failed(
                    user_id,
                    task.task_id,
                    "Approval request could not be delivered",
                )
            return False

        return False
    
    async def _emit_client_batch_remote(self, user_id: str, tasks: list[TaskRecord], job_id: str = "default") -> None:
        """
        PRODUCTION MODE: Emit client tasks via WebSocket.
        """
        if not self.socket_handler:
            logger.error("No socket handler configured for production mode!")
            for task in tasks:
                await self.orchestrator.mark_task_failed(
                    user_id, task.task_id,
                    "Socket handler not configured",
                    job_id=job_id
                )
            return
        
        for task in tasks:
            try:
                state = self.orchestrator._find_state_for_task(user_id, task.task_id, job_id=job_id)
                if state:
                    can_resolve, error = self.binding_resolver.validate_bindings(task, state)
                    if can_resolve:
                        resolved_inputs = self.binding_resolver.resolve_inputs(task, state)
                        resolved_inputs["_user_id"] = user_id
                        resolved_inputs["user_id"] = user_id
                        resolved_inputs["_task_id"] = task.task_id
                        resolved_inputs["_execution_id"] = state.execution_id
                        resolved_inputs["execution_id"] = state.execution_id
                        task.resolved_inputs = resolved_inputs
                        logger.info(f"     📋 Resolved inputs for {task.task_id}")
                
                if task.lifecycle_messages and task.lifecycle_messages.on_start:
                    logger.info(f"     {task.lifecycle_messages.on_start}")
                
                await self.orchestrator.mark_task_emitted(user_id, task.task_id, job_id=job_id)
                
                success = await self.socket_handler.emit_task_single(user_id, task)
                
                if success:
                    logger.info(f"  Emitted: {task.task_id} ({task.tool})")
                else:
                    logger.warning(f"   Failed to emit: {task.task_id}")
            
            except Exception as e:
                logger.error(f"  Error emitting {task.task_id}: {e}")
    
    def _is_dependency_chain(self, tasks: list[TaskRecord]) -> bool:
        """Check if tasks form a dependency chain"""
        if len(tasks) <= 1:
            return False
        
        for i in range(1, len(tasks)):
            prev_id = tasks[i-1].task_id
            curr_deps = tasks[i].depends_on
            if prev_id not in curr_deps:
                return False
        
        return True
    
    async def _print_final_summary(self, user_id: str, *, job_id: str = ""):
        """Print execution summary"""
        summary = await self.orchestrator.get_execution_summary(user_id)
        summary_payload: Dict[str, Any] = dict(summary)

        logger.info("\n" + "="*70)
        logger.info("FINAL EXECUTION SUMMARY")
        logger.info("="*70)
        logger.info(f"User:        {user_id}")
        logger.info(f"Total Tasks: {summary['total']}")
        logger.info(f"Completed: {summary['completed']}")
        logger.info(f"Failed:    {summary['failed']}")
        logger.info(f"Pending:   {summary['pending']}")
        logger.info(f"Running:   {summary['running']}")

        if summary['total'] > 0:
            success_rate = (summary['completed'] / summary['total']) * 100
            logger.info(f"Success Rate: {success_rate:.1f}%")
            summary_payload["success_rate"] = round(success_rate, 2)

        if job_id:
            summary_payload["job_id"] = job_id

        logger.info("="*70)
        await _emit_summary_event(user_id, summary_payload)

        # Build a richer summary message from completed tool outputs
        parts = []
        state = self.orchestrator.get_state(user_id, job_id=job_id) if job_id else self.orchestrator.get_state(user_id)
        if state:
            for t in state.tasks.values():
                if t.status == "completed" and t.output and t.output.data:
                    rs = _build_result_summary(t.tool, t.output.data)
                    if rs:
                        parts.append(rs)
        exec_msg = " · ".join(parts) if parts else f"Done: {summary['completed']}/{summary['total']} succeeded"
        await emit_spark_log(user_id, "execution_complete", payload={"message": exec_msg, **summary_payload})
    
    def is_running(self, user_id: str, job_id: Optional[str] = None) -> bool:
        """Check if execution is running for user (optionally for a specific job)."""
        if job_id:
            engine_key = f"{user_id}:{job_id}"
            task = self.running_engines.get(engine_key)
            return task is not None and not task.done()
        # Check if ANY job is running for this user
        prefix = f"{user_id}:"
        return any(
            not t.done() for k, t in self.running_engines.items()
            if k.startswith(prefix)
        )

    async def stop_execution(self, user_id: str, job_id: Optional[str] = None) -> None:
        """Stop execution for a user (optionally for a specific job)."""
        coordinator = get_job_coordinator()
        get_approval_coordinator().cancel_user_requests(user_id)

        if job_id:
            # Check if this is a queued (not yet running) job
            job_meta = coordinator.get_job(user_id, job_id)
            if job_meta and job_meta.status == JobStatus.QUEUED:
                coordinator.cancel_queued_job(user_id, job_id)
                logger.info("🛑 Cancelled queued job %s for %s", job_id, user_id)
                return

            engine_key = f"{user_id}:{job_id}"
            # Trigger cancellation context first
            cancel_ctx = self._cancellation_contexts.get(engine_key)
            if cancel_ctx:
                cancel_ctx.cancel()
            task = self.running_engines.get(engine_key)
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                coordinator.update_status(user_id, job_id, JobStatus.CANCELLED)
                logger.info(f"🛑 Stopped execution for {engine_key}")
        else:
            # Stop ALL running jobs for this user
            prefix = f"{user_id}:"
            keys = [k for k in self.running_engines if k.startswith(prefix)]
            for key in keys:
                cancel_ctx = self._cancellation_contexts.get(key)
                if cancel_ctx:
                    cancel_ctx.cancel()
                task = self.running_engines.get(key)
                if task and not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
                    jid = key.split(":", 1)[1] if ":" in key else key
                    coordinator.update_status(user_id, jid, JobStatus.CANCELLED)

            # Also cancel all queued jobs
            for qj in coordinator.get_queued_jobs(user_id):
                coordinator.cancel_queued_job(user_id, qj.job_id)

            stopped = len(keys) + len(coordinator.get_queued_jobs(user_id))
            if keys:
                logger.info(f"🛑 Stopped all {len(keys)} running + queued jobs for {user_id}")


# Global singleton
_execution_engine: Optional[ExecutionEngine] = None


def get_execution_engine() -> ExecutionEngine:
    """Get global execution engine instance"""
    global _execution_engine
    if _execution_engine is None:
        _execution_engine = ExecutionEngine()
    return _execution_engine


def init_execution_engine() -> ExecutionEngine:
    """Initialize execution engine at startup"""
    global _execution_engine
    _execution_engine = ExecutionEngine()
    return _execution_engine



