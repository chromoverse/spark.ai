# app/kernel/orchestrator.py
"""
Production-Grade Task Orchestrator
- User-wise state management
- Dependency analysis
- Parallel execution support
- Server/Client task routing
- FIXED: Returns entire client chains in one batch
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Set
from datetime import datetime

from app.kernel.execution.execution_models import (
    Task, TaskRecord, ExecutionState, TaskStatus, 
    TaskOutput, TaskBatch, ExecutionTarget
)
from app.plugins.tools.registry_loader import get_tool_registry
from app.kernel.contracts.models import KernelEvent
from app.kernel.eventing.event_bus import emit_kernel_event

logger = logging.getLogger(__name__)


class TaskOrchestrator:
    """
    Central orchestrator managing task execution across users
    
    Responsibilities:
    - Accept task plans from LLM
    - Store per-user execution state
    - Analyze dependencies
    - Route server/client tasks
    - Return executable batches WITH client chains detected
    """
    
    def __init__(self):
        # User-wise state storage
        self.states: Dict[str, ExecutionState] = {}
        
        # Tool registry (loaded at startup)
        self.tool_registry = get_tool_registry()
        
        # Locks for thread-safe operations
        self._locks: Dict[str, asyncio.Lock] = {}
        
        logger.info("TaskOrchestrator initialized")
    
    def _get_lock(self, user_id: str) -> asyncio.Lock:
        """Get or create lock for user"""
        if user_id not in self._locks:
            self._locks[user_id] = asyncio.Lock()
        return self._locks[user_id]
    
    async def register_tasks(self, user_id: str, tasks: List[Task]) -> None:
        """
        Register a list of tasks for a user
        
        Args:
            user_id: User identifier
            tasks: List of Task objects from LLM
        """
        async with self._get_lock(user_id):
            # Create or get user state
            if user_id not in self.states:
                self.states[user_id] = ExecutionState(user_id=user_id)
                logger.info("Created new execution state for user: %s", user_id)
            
            state = self.states[user_id]
            
            logger.info(f"Registering {len(tasks)} tasks for user {user_id}")
            
            for task in tasks:
                # Validate tool exists
                if not self.tool_registry.validate_tool(task.tool):
                    logger.error(f"Invalid tool: {task.tool}")
                    # Create failed task record (still store full task)
                    record = TaskRecord(
                        task=task,  # Store complete Task
                        status="failed",
                        error=f"Tool '{task.tool}' not found in registry"
                    )
                else:
                    # Create task record with full task data
                    record = TaskRecord(
                        task=task,  # Store complete Task - client gets EVERYTHING
                        status="pending"
                    )
                    logger.info(f"  {task.task_id}: {task.tool} [{task.execution_target}]")
                
                state.add_task(record)
                await emit_kernel_event(
                    KernelEvent(
                        event_type="task_registered",
                        user_id=user_id,
                        task_id=task.task_id,
                        tool_name=task.tool,
                        status=record.status,
                        payload={
                            "execution_target": task.execution_target,
                            "depends_on": task.depends_on,
                        },
                    )
                )
            
            logger.info(f"Registered {len(tasks)} tasks for user {user_id}")
    
    async def get_executable_batch(self, user_id: str) -> TaskBatch:
        """
        Get batch of tasks ready to execute RIGHT NOW
        
        FIXED: Returns entire CLIENT CHAINS in one batch!
        
        For client tasks, if A→B→C are all client and A is ready,
        returns ALL THREE so engine can batch them together.
        """
        async with self._get_lock(user_id):
            state = self.states.get(user_id)
            
            if not state:
                return TaskBatch()
            
            batch = TaskBatch()
            processed_ids = set()
            
            # Find all pending tasks
            pending_tasks = state.get_tasks_by_status("pending")
            
            for task in pending_tasks:
                if task.task_id in processed_ids:
                    continue
                
                # Check if dependencies are met
                if not self._are_dependencies_met(state, task.task_id):
                    continue
                
                if task.execution_target == "server":
                    # Server tasks: add individually
                    batch.server_tasks.append(task)
                    processed_ids.add(task.task_id)
                
                elif task.execution_target == "client":
                    # CLIENT CHAIN OPTIMIZATION:
                    # If this starts a chain, include entire chain!
                    chain = self._get_client_chain_from_task(state, task, pending_tasks)
                    batch.client_tasks.extend(chain)
                    
                    # Mark all in chain as processed
                    for chain_task in chain:
                        processed_ids.add(chain_task.task_id)
            
            if batch.client_tasks and len(batch.client_tasks) > 1:
                logger.info(f"   Detected client chain: {[t.task_id for t in batch.client_tasks]}")
            
            logger.info(
                f"Batch for {user_id}: "
                f"{len(batch.server_tasks)} server, "
                f"{len(batch.client_tasks)} client"
            )
            
            return batch
    
    def _get_client_chain_from_task(
        self, 
        state: ExecutionState, 
        start_task: TaskRecord,
        all_pending: List[TaskRecord]
    ) -> List[TaskRecord]:
        """
        Get entire client chain starting from a task
        
        KEY OPTIMIZATION: Returns A→B→C all at once!
        
        Example:
        - start_task: create_folder (no deps, runnable)
        - Finds: write_file (depends on create_folder)
        - Finds: copy_file (depends on write_file)
        - Returns: [create_folder, write_file, copy_file]
        """
        chain = [start_task]
        pending_map = {t.task_id: t for t in all_pending}
        current_id = start_task.task_id
        
        # Look ahead for tasks that depend on current chain
        while True:
            found_next = False
            
            for pending_task in all_pending:
                if pending_task.task_id in [t.task_id for t in chain]:
                    continue  # Already in chain
                
                # Check if this task:
                # 1. Is a client task
                # 2. Has current task as a dependency
                # 3. All its dependencies are satisfied
                if pending_task.execution_target != "client":
                    continue
                
                if current_id not in pending_task.depends_on:
                    continue
                
                # Verify ALL dependencies are satisfied
                # (could depend on completed server tasks too)
                can_add = True
                completed_ids = state.get_completed_task_ids()
                chain_ids = {t.task_id for t in chain}
                
                for dep_id in pending_task.depends_on:
                    # Dependency must be either:
                    # - In current chain, OR
                    # - Already completed
                    if dep_id not in chain_ids and dep_id not in completed_ids:
                        can_add = False
                        break
                
                if can_add:
                    chain.append(pending_task)
                    current_id = pending_task.task_id
                    found_next = True
                    break
            
            if not found_next:
                break
        
        return chain
    
    def _are_dependencies_met(self, state: ExecutionState, task_id: str) -> bool:
        """
        Check if all dependencies for a task are completed
        
        FIXED: Only checks COMPLETED tasks (not failed)
        """
        task = state.get_task(task_id)
        
        if not task or not task.depends_on:
            return True
        
        completed_ids = state.get_completed_task_ids()
        
        for dep_id in task.depends_on:
            if dep_id not in completed_ids:
                # Check if dependency exists and is failed
                dep_task = state.get_task(dep_id)
                if dep_task and dep_task.status == "failed":
                    # Dependency failed - this task can never run
                    logger.warning(
                        f" Task {task_id} depends on failed task {dep_id}, "
                        f"will never be executable"
                    )
                return False
        
        return True
    
    async def mark_task_running(self, user_id: str, task_id: str) -> None:
        """Mark task as running"""
        async with self._get_lock(user_id):
            state = self.states.get(user_id)
            if not state:
                return
            
            task = state.get_task(task_id)
            if task:
                task.status = "running"
                task.started_at = datetime.now()
                state.updated_at = datetime.now()
                logger.info(f"[{user_id}] Task {task_id} started")
                await emit_kernel_event(
                    KernelEvent(
                        event_type="task_started",
                        user_id=user_id,
                        task_id=task_id,
                        tool_name=task.tool,
                        status="running",
                    )
                )

    async def mark_task_waiting(self, user_id: str, task_id: str) -> None:
        """Mark task as waiting (typically pending user approval)."""
        async with self._get_lock(user_id):
            state = self.states.get(user_id)
            if not state:
                return

            task = state.get_task(task_id)
            if task:
                task.status = "waiting"
                task.started_at = datetime.now()
                state.updated_at = datetime.now()
                logger.info(f"[{user_id}] Task {task_id} waiting for approval")
                await emit_kernel_event(
                    KernelEvent(
                        event_type="task_waiting",
                        user_id=user_id,
                        task_id=task_id,
                        tool_name=task.tool,
                        status="waiting",
                    )
                )
    
    async def mark_task_completed(
        self, 
        user_id: str, 
        task_id: str, 
        output: TaskOutput
    ) -> None:
        """Mark task as completed with output"""
        async with self._get_lock(user_id):
            state = self.states.get(user_id)
            if not state:
                return
            
            task = state.get_task(task_id)
            if task:
                task.status = "completed"
                task.output = output
                task.completed_at = datetime.now()
                
                if task.started_at:
                    duration = (task.completed_at - task.started_at).total_seconds() * 1000
                    task.duration_ms = int(duration)
                
                state.updated_at = datetime.now()
                logger.info(f"[{user_id}] Task {task_id} completed in {task.duration_ms}ms")
                await emit_kernel_event(
                    KernelEvent(
                        event_type="task_completed",
                        user_id=user_id,
                        task_id=task_id,
                        tool_name=task.tool,
                        status="completed",
                        payload={
                            "duration_ms": task.duration_ms,
                            "output_success": output.success,
                        },
                    )
                )
    
    async def mark_task_failed(
        self, 
        user_id: str, 
        task_id: str, 
        error: str
    ) -> None:
        """
        Mark task as failed
        
        IMPORTANT: Also marks dependent tasks as failed to prevent infinite loops
        """
        async with self._get_lock(user_id):
            state = self.states.get(user_id)
            if not state:
                return
            
            task = state.get_task(task_id)
            if task:
                task.status = "failed"
                task.error = error
                task.completed_at = datetime.now()
                
                if task.started_at:
                    duration = (task.completed_at - task.started_at).total_seconds() * 1000
                    task.duration_ms = int(duration)
                
                state.updated_at = datetime.now()
                logger.error(f"[{user_id}] Task {task_id} failed: {error}")
                await emit_kernel_event(
                    KernelEvent(
                        event_type="task_failed",
                        user_id=user_id,
                        task_id=task_id,
                        tool_name=task.tool,
                        status="failed",
                        payload={
                            "duration_ms": task.duration_ms,
                            "error": error,
                        },
                    )
                )
                
                # CASCADE FAILURE: Mark dependent tasks as failed too
                await self._cascade_failure(user_id, task_id)
    
    async def _cascade_failure(self, user_id: str, failed_task_id: str) -> None:
        """
        Mark all tasks that depend on a failed task as failed
        
        This prevents infinite loops where pending tasks wait for failed dependencies
        """
        state = self.states.get(user_id)
        if not state:
            return
        
        # Find all pending tasks that depend on this one
        pending_tasks = state.get_tasks_by_status("pending")
        
        for task in pending_tasks:
            if failed_task_id in task.depends_on:
                task.status = "failed"
                task.error = f"Dependency '{failed_task_id}' failed"
                task.completed_at = datetime.now()
                logger.warning(
                    f" [{user_id}] Task {task.task_id} marked as failed "
                    f"due to failed dependency: {failed_task_id}"
                )
                
                # Recursively cascade
                await self._cascade_failure(user_id, task.task_id)
    
    async def mark_task_emitted(self, user_id: str, task_id: str) -> None:
        """Mark client task as emitted to client"""
        async with self._get_lock(user_id):
            state = self.states.get(user_id)
            if not state:
                return
            
            task = state.get_task(task_id)
            if task:
                task.status = "emitted"
                task.emitted_at = datetime.now()
                task.started_at = datetime.now()
                state.updated_at = datetime.now()
                logger.info(f"[{user_id}] Task {task_id} emitted to client")
                await emit_kernel_event(
                    KernelEvent(
                        event_type="task_emitted",
                        user_id=user_id,
                        task_id=task_id,
                        tool_name=task.tool,
                        status="emitted",
                    )
                )
    
    async def handle_client_ack(
        self, 
        user_id: str, 
        task_id: str, 
        output: TaskOutput
    ) -> None:
        """
        Handle acknowledgment from client with results
        
        NOTE: Does NOT acquire lock - called from within locked context
        """
        state = self.states.get(user_id)
        if not state:
            return
        
        task = state.get_task(task_id)
        if task:
            task.ack_received_at = datetime.now()
            latency_ms = None
            if task.started_at and task.ack_received_at:
                latency_ms = int((task.ack_received_at - task.started_at).total_seconds() * 1000)
            
            if output.success:
                await emit_kernel_event(
                    KernelEvent(
                        event_type="tool_invoked",
                        user_id=user_id,
                        task_id=task_id,
                        tool_name=task.tool,
                        status="success",
                        payload={"latency_ms": latency_ms},
                    )
                )
                await self.mark_task_completed(user_id, task_id, output)
            else:
                error = output.error or "Client execution failed"
                await emit_kernel_event(
                    KernelEvent(
                        event_type="tool_failed",
                        user_id=user_id,
                        task_id=task_id,
                        tool_name=task.tool,
                        status="failed",
                        payload={"latency_ms": latency_ms, "error": error},
                    )
                )
                await self.mark_task_failed(user_id, task_id, error)
    
    def get_state(self, user_id: str) -> Optional[ExecutionState]:
        """Get user execution state"""
        return self.states.get(user_id)
    
    def get_task(self, user_id: str, task_id: str) -> Optional[TaskRecord]:
        """Get specific task for user"""
        state = self.states.get(user_id)
        return state.get_task(task_id) if state else None
    
    async def get_execution_summary(self, user_id: str) -> Dict[str, int]:
        """Get execution summary for user"""
        async with self._get_lock(user_id):
            state = self.states.get(user_id)
            
            if not state:
                return {
                    "total": 0,
                    "pending": 0,
                    "running": 0,
                    "completed": 0,
                    "failed": 0
                }
            
            summary = {
                "total": len(state.tasks),
                "pending": 0,
                "running": 0,
                "completed": 0,
                "failed": 0,
                "waiting": 0,
                "skipped": 0,
                "emitted": 0
            }
            
            for task in state.tasks.values():
                summary[task.status] += 1
            
            return summary

    async def build_execution_speech_snapshot(
        self,
        user_id: str,
        max_tasks: int = 12,
        max_data_fields: int = 4,
    ) -> Dict[str, Any]:
        """
        Build a compact, speech-safe snapshot from execution state.

        This is used by final TTS summarization after all tasks complete.
        """
        async with self._get_lock(user_id):
            state = self.states.get(user_id)
            if not state:
                return {
                    "user_id": user_id,
                    "has_state": False,
                    "summary": {
                        "total": 0,
                        "pending": 0,
                        "running": 0,
                        "completed": 0,
                        "failed": 0,
                        "waiting": 0,
                        "skipped": 0,
                        "emitted": 0,
                    },
                    "tasks": [],
                }

            summary = {
                "total": len(state.tasks),
                "pending": 0,
                "running": 0,
                "completed": 0,
                "failed": 0,
                "waiting": 0,
                "skipped": 0,
                "emitted": 0,
            }
            for task in state.tasks.values():
                summary[task.status] += 1

            ordered_tasks = sorted(
                state.tasks.values(),
                key=lambda t: (t.created_at, t.task_id),
            )[: max(1, max_tasks)]

            tasks: List[Dict[str, Any]] = []
            for task in ordered_tasks:
                output_preview: Dict[str, Any] = {}
                if task.output and isinstance(task.output.data, dict):
                    for i, key in enumerate(task.output.data.keys()):
                        if i >= max_data_fields:
                            break
                        value = task.output.data.get(key)
                        if isinstance(value, (str, int, float, bool)) or value is None:
                            output_preview[key] = value
                        elif isinstance(value, (dict, list, tuple, set)):
                            output_preview[key] = str(value)[:140]
                        else:
                            output_preview[key] = str(value)[:140]

                tasks.append(
                    {
                        "task_id": task.task_id,
                        "tool": task.tool,
                        "execution_target": task.execution_target,
                        "status": task.status,
                        "duration_ms": task.duration_ms,
                        "error": task.error,
                        "output_success": task.output.success if task.output else None,
                        "output_preview": output_preview,
                    }
                )

            return {
                "user_id": user_id,
                "has_state": True,
                "summary": summary,
                "tasks": tasks,
            }
    
    async def cleanup_user_state(self, user_id: str) -> None:
        """Cleanup user state (call on disconnect)"""
        async with self._get_lock(user_id):
            if user_id in self.states:
                del self.states[user_id]
                logger.info(f"Cleaned up state for user: {user_id}")
            
            if user_id in self._locks:
                del self._locks[user_id]
    
    async def handle_approval(self, user_id: str, task_id: str, approved: bool) -> None:
        """
        Handle user approval/denial for a task.
        
        Called when user clicks Accept/Deny on a notification.
        
        Args:
            user_id: User identifier
            task_id: Task identifier
            approved: True if user accepted, False if denied
        """
        if approved:
            logger.info(f"[{user_id}] Task {task_id} APPROVED by user")
            # Mark as completed with approval output
            output = TaskOutput(
                success=True,
                data={"approved": True, "source": "user_notification"}
            )
            await self.mark_task_completed(user_id, task_id, output)
        else:
            logger.info(f"[{user_id}] Task {task_id} DENIED by user")
            await self.mark_task_failed(user_id, task_id, "User denied approval via notification")


# Global orchestrator instance
_orchestrator: Optional[TaskOrchestrator] = None


def get_orchestrator() -> TaskOrchestrator:
    """Get global orchestrator instance"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = TaskOrchestrator()
    return _orchestrator


def init_orchestrator() -> TaskOrchestrator:
    """Initialize orchestrator at startup"""
    global _orchestrator
    _orchestrator = TaskOrchestrator()
    return _orchestrator




