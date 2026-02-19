# app/core/execution_engine.py
"""
UNIFIED Execution Engine

Single engine for BOTH server and client tasks.
- Desktop: Executes client tasks DIRECTLY (no emit, no separate loop)
- Production: Emits client tasks via WebSocket

ONE orchestrator, ONE state — no more split-brain.

✅ Event-based completion signaling for proper async waiting
"""

import asyncio
import logging
from typing import Dict, Optional
from datetime import datetime

from app.agent.core.orchestrator import get_orchestrator
from app.agent.core.models import TaskRecord, TaskOutput
from app.agent.core.binding_resolver import get_binding_resolver

logger = logging.getLogger(__name__)


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
        
        # Track running engines per user
        self.running_engines: Dict[str, asyncio.Task] = {}
        
        # Completion events for awaiting execution
        self.completion_events: Dict[str, asyncio.Event] = {}
        
        # Tool executors (injected at startup)
        self.server_tool_executor = None
        self.client_tool_executor = None    # ✅ NEW: For desktop direct execution
        self.socket_handler = None          # For production WebSocket emit
        
        # Environment
        from app.config import settings
        self.environment = settings.environment
        
        logger.info(f"✅ Unified Execution Engine initialized (env={self.environment})")
    
    def set_server_executor(self, executor):
        """Inject server tool executor"""
        self.server_tool_executor = executor
    
    def set_client_executor(self, executor):
        """✅ NEW: Inject client tool executor (for desktop direct execution)"""
        self.client_tool_executor = executor
        logger.info("✅ Client tool executor injected (desktop direct execution)")
    
    def set_client_emitter(self, emitter):
        """Set client task emitter (for backward compat / production)"""
        self.socket_handler = emitter
    
    # Keep old name working
    @property
    def client_task_emitter(self):
        return self.socket_handler
    
    async def start_execution(self, user_id: str) -> asyncio.Task:
        """
        Start execution engine for a user (non-blocking)
        Creates a background task that runs the execution loop
        """
        # Create completion event BEFORE starting
        self.completion_events[user_id] = asyncio.Event()
        
        # Check if already running for this user
        if user_id in self.running_engines:
            existing = self.running_engines[user_id]
            if not existing.done():
                logger.info(f"⚠️  Execution already running for {user_id}")
                return existing
        
        # Start new background task
        task = asyncio.create_task(
            self._execution_loop(user_id)
        )
        self.running_engines[user_id] = task
        
        logger.info(f"🚀 Started execution engine for user: {user_id}")
        return task
    
    async def wait_for_completion(self, user_id: str, timeout: float = 30) -> bool:
        """Wait for execution to complete with timeout"""
        if user_id not in self.completion_events:
            logger.warning(f"⚠️  No execution running for {user_id}")
            return False
        
        try:
            logger.info(f"⏳ Waiting for execution to complete (timeout: {timeout}s)...")
            await asyncio.wait_for(
                self.completion_events[user_id].wait(),
                timeout=timeout
            )
            logger.info(f"✅ Execution completed for {user_id}")
            return True
            
        except asyncio.TimeoutError:
            logger.warning(f"⏰ Timeout waiting for {user_id} execution after {timeout}s")
            return False
    
    async def _execution_loop(self, user_id: str) -> None:
        """
        Main execution loop for a user
        Runs continuously until all tasks are done or timeout
        """
        logger.info(f"\n{'='*70}")
        logger.info(f"🔥 EXECUTION LOOP STARTED: {user_id}")
        logger.info(f"{'='*70}\n")
        
        iteration = 0
        max_iterations = 100  # Safety limit
        no_work_count = 0
        max_idle = 3
        
        try:
            while iteration < max_iterations:
                iteration += 1
                
                # ✅ FAST EXIT: No tasks registered = nothing to do
                state = self.orchestrator.get_state(user_id)
                if not state or len(state.tasks) == 0:
                    logger.info(f"⚡ No tasks registered for {user_id} — exiting immediately")
                    break
                
                # ✅ Check if ALL tasks are terminal (completed/failed)
                pending = state.get_tasks_by_status("pending")
                running = state.get_tasks_by_status("running")
                emitted = state.get_tasks_by_status("emitted")
                
                if not pending and not running and not emitted:
                    logger.info(f"✅ All tasks finished for {user_id} — exiting")
                    break
                
                logger.info(f"\n{'─'*70}")
                logger.info(f"Iteration {iteration} - User: {user_id}")
                logger.info(f"{'─'*70}")
                
                # 1. Get executable batch
                batch = await self.orchestrator.get_executable_batch(user_id)

                logger.info(f"🔍 Found {len(batch.server_tasks)} server tasks, {len(batch.client_tasks)} client tasks")
                
                has_work = bool(batch.server_tasks or batch.client_tasks)
                
                if not has_work:
                    no_work_count += 1
                    logger.info(f"⏸️  No runnable tasks (idle count: {no_work_count}/{max_idle})")
                    
                    if no_work_count >= max_idle:
                        # If tasks are stuck (pending but deps never satisfied), exit
                        logger.info("✅ No more work — execution complete!")
                        break
                    
                    await asyncio.sleep(0.2)
                    continue
                
                # Reset idle counter
                no_work_count = 0
                
                logger.info(f"📦 Batch: {len(batch.server_tasks)} server, {len(batch.client_tasks)} client")
                
                # 2. Execute server + client tasks in PARALLEL
                parallel_work = []
                
                if batch.server_tasks:
                    logger.info(f"\n🚀 Executing {len(batch.server_tasks)} server tasks...")
                    parallel_work.append(self._execute_server_batch(user_id, batch.server_tasks))
                
                if batch.client_tasks:
                    logger.info(f"\n🖥️  Handling {len(batch.client_tasks)} client tasks...")
                    parallel_work.append(self._handle_client_batch(user_id, batch.client_tasks))
                
                if parallel_work:
                    results = await asyncio.gather(*parallel_work, return_exceptions=True)
                    for i, result in enumerate(results):
                        if isinstance(result, Exception):
                            logger.error(f"❌ Parallel work item {i} failed: {result}")
                
                # Small delay before next iteration
                await asyncio.sleep(0.1)
            
            if iteration >= max_iterations:
                logger.warning(f"⚠️  Max iterations reached for {user_id}")
        
        except Exception as e:
            logger.error(f"❌ Execution loop error for {user_id}: {e}", exc_info=True)
        
        finally:
            # Cleanup
            if user_id in self.running_engines:
                del self.running_engines[user_id]
            
            await self._print_final_summary(user_id)
            
            # Signal completion event
            if user_id in self.completion_events:
                self.completion_events[user_id].set()
                logger.info(f"📢 Completion event signaled for {user_id}")
            
            logger.info(f"\n{'='*70}")
            logger.info(f"🏁 EXECUTION LOOP ENDED: {user_id}")
            logger.info(f"{'='*70}\n")
    
    # ==================== SERVER TASK EXECUTION ====================
    
    async def _execute_server_batch(self, user_id: str, tasks: list[TaskRecord]) -> None:
        """Execute multiple server tasks in parallel"""
        if not self.server_tool_executor:
            logger.error("❌ No server tool executor configured!")
            return
        
        results = await asyncio.gather(
            *[self._execute_single_server_task(user_id, task) for task in tasks],
            return_exceptions=True
        )
        
        success_count = sum(1 for r in results if not isinstance(r, Exception))
        logger.info(f"✅ Completed {success_count}/{len(tasks)} server tasks")
    
    async def _execute_single_server_task(self, user_id: str, task: TaskRecord) -> None:
        """Execute a single server task"""
        try:
            await self.orchestrator.mark_task_running(user_id, task.task_id)
            
            logger.info(f"  🔄 Executing: {task.task_id} ({task.tool})")
            
            if task.lifecycle_messages and task.lifecycle_messages.on_start:
                logger.info(f"     💬 {task.lifecycle_messages.on_start}")

            if not self.server_tool_executor: 
                raise RuntimeError("Server tool executor not configured")    
            
            # RESOLVE INPUT BINDINGS
            state = self.orchestrator.get_state(user_id)
            if not state:
                raise RuntimeError(f"No execution state for user: {user_id}")
            
            can_resolve, error = self.binding_resolver.validate_bindings(task, state)
            if not can_resolve:
                raise ValueError(f"Cannot resolve bindings: {error}")
            
            resolved_inputs = self.binding_resolver.resolve_inputs(task, state)
            resolved_inputs["_user_id"] = user_id
            task.resolved_inputs = resolved_inputs
            
            logger.info(f"     📋 Resolved inputs: {list(resolved_inputs.keys())}")
            
            # Get timeout
            timeout = None
            if task.control and task.control.timeout_ms:
                timeout = task.control.timeout_ms / 1000
            
            # Execute
            if timeout:
                output = await asyncio.wait_for(
                    self.server_tool_executor.execute(task),
                    timeout=timeout
                )
            else:
                output = await self.server_tool_executor.execute(task)
            
            await self.orchestrator.mark_task_completed(user_id, task.task_id, output)
            
            if task.lifecycle_messages and task.lifecycle_messages.on_success:
                logger.info(f"     💬 {task.lifecycle_messages.on_success}")
            
            logger.info(f"  ✅ Completed: {task.task_id} ({task.duration_ms}ms)")
        
        except asyncio.TimeoutError:
            error = f"Task timed out after {timeout}s" # type: ignore
            await self.orchestrator.mark_task_failed(user_id, task.task_id, error)
            if task.lifecycle_messages and task.lifecycle_messages.on_failure:
                logger.info(f"     💬 {task.lifecycle_messages.on_failure}")
        
        except Exception as e:
            error = str(e)
            await self.orchestrator.mark_task_failed(user_id, task.task_id, error)
            if task.lifecycle_messages and task.lifecycle_messages.on_failure:
                logger.info(f"     💬 {task.lifecycle_messages.on_failure}")
    
    # ==================== CLIENT TASK HANDLING ====================
    
    async def _handle_client_batch(self, user_id: str, tasks: list[TaskRecord]) -> None:
        """
        ✅ UNIFIED: Handle client tasks based on environment.
        
        Desktop: Execute DIRECTLY (same orchestrator, same state)
        Production: Emit via WebSocket
        """
        if self.environment == "desktop":
            await self._execute_client_batch_locally(user_id, tasks)
        else:
            await self._emit_client_batch_remote(user_id, tasks)
    
    async def _execute_client_batch_locally(self, user_id: str, tasks: list[TaskRecord]) -> None:
        """
        ✅ DESKTOP MODE: Execute client tasks DIRECTLY.
        
        Same orchestrator marks completion → dependent tasks unblock immediately.
        No emit, no separate loop, no split-brain state.
        """
        if not self.client_tool_executor:
            logger.error("❌ No client tool executor configured for desktop mode!")
            for task in tasks:
                await self.orchestrator.mark_task_failed(
                    user_id, task.task_id,
                    "Client tool executor not configured"
                )
            return
        
        # Execute all tasks in parallel
        results = await asyncio.gather(
            *[self._execute_single_client_task(user_id, task) for task in tasks],
            return_exceptions=True
        )
        
        success_count = sum(1 for r in results if not isinstance(r, Exception))
        logger.info(f"✅ Completed {success_count}/{len(tasks)} client tasks locally")
    
    async def _execute_single_client_task(self, user_id: str, task: TaskRecord) -> None:
        """Execute a single client task locally (desktop mode)"""
        try:
            await self.orchestrator.mark_task_running(user_id, task.task_id)
            
            logger.info(f"  🖥️  Executing locally: {task.task_id} ({task.tool})")
            
            if task.lifecycle_messages and task.lifecycle_messages.on_start:
                logger.info(f"     💬 {task.lifecycle_messages.on_start}")
            
            # Resolve inputs
            state = self.orchestrator.get_state(user_id)
            if not state:
                raise RuntimeError(f"No execution state for user: {user_id}")
            
            can_resolve, error = self.binding_resolver.validate_bindings(task, state)
            if not can_resolve:
                raise ValueError(f"Cannot resolve bindings: {error}")
            
            resolved_inputs = self.binding_resolver.resolve_inputs(task, state)
            resolved_inputs["_user_id"] = user_id
            task.resolved_inputs = resolved_inputs
            
            logger.info(f"     📋 Resolved inputs: {list(resolved_inputs.keys())}")
            
            # Execute via client tool executor
            output = await self.client_tool_executor.execute(task, resolved_inputs)
            
            # ✅ KEY: Mark on SAME orchestrator — dependent tasks unblock instantly
            await self.orchestrator.mark_task_completed(user_id, task.task_id, output)
            
            if task.lifecycle_messages and task.lifecycle_messages.on_success:
                logger.info(f"     💬 {task.lifecycle_messages.on_success}")
            
            logger.info(f"  ✅ Completed locally: {task.task_id}")
        
        except Exception as e:
            error_msg = str(e)
            await self.orchestrator.mark_task_failed(user_id, task.task_id, error_msg)
            
            if task.lifecycle_messages and task.lifecycle_messages.on_failure:
                logger.info(f"     💬 {task.lifecycle_messages.on_failure}")
            
            logger.error(f"  ❌ Failed locally: {task.task_id} - {error_msg}")
    
    async def _emit_client_batch_remote(self, user_id: str, tasks: list[TaskRecord]) -> None:
        """
        PRODUCTION MODE: Emit client tasks via WebSocket.
        """
        if not self.socket_handler:
            logger.error("❌ No socket handler configured for production mode!")
            for task in tasks:
                await self.orchestrator.mark_task_failed(
                    user_id, task.task_id,
                    "Socket handler not configured"
                )
            return
        
        state = self.orchestrator.get_state(user_id)
        
        for task in tasks:
            try:
                if state:
                    can_resolve, error = self.binding_resolver.validate_bindings(task, state)
                    if can_resolve:
                        resolved_inputs = self.binding_resolver.resolve_inputs(task, state)
                        task.resolved_inputs = resolved_inputs
                        logger.info(f"     📋 Resolved inputs for {task.task_id}")
                
                if task.lifecycle_messages and task.lifecycle_messages.on_start:
                    logger.info(f"     💬 {task.lifecycle_messages.on_start}")
                
                await self.orchestrator.mark_task_emitted(user_id, task.task_id)
                
                success = await self.socket_handler.emit_task_single(user_id, task)
                
                if success:
                    logger.info(f"  📤 Emitted: {task.task_id} ({task.tool})")
                else:
                    logger.warning(f"  ⚠️  Failed to emit: {task.task_id}")
            
            except Exception as e:
                logger.error(f"  ❌ Error emitting {task.task_id}: {e}")
    
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
    
    async def _print_final_summary(self, user_id: str):
        """Print execution summary"""
        summary = await self.orchestrator.get_execution_summary(user_id)
        
        logger.info("\n" + "="*70)
        logger.info("FINAL EXECUTION SUMMARY")
        logger.info("="*70)
        logger.info(f"User:        {user_id}")
        logger.info(f"Total Tasks: {summary['total']}")
        logger.info(f"✅ Completed: {summary['completed']}")
        logger.info(f"❌ Failed:    {summary['failed']}")
        logger.info(f"⏳ Pending:   {summary['pending']}")
        logger.info(f"🔄 Running:   {summary['running']}")
        
        if summary['total'] > 0:
            success_rate = (summary['completed'] / summary['total']) * 100
            logger.info(f"Success Rate: {success_rate:.1f}%")
        
        logger.info("="*70)
    
    def is_running(self, user_id: str) -> bool:
        """Check if execution is running for user"""
        task = self.running_engines.get(user_id)
        return task is not None and not task.done()
    
    async def stop_execution(self, user_id: str) -> None:
        """Stop execution for a user (graceful shutdown)"""
        task = self.running_engines.get(user_id)
        if task and not task.done():
            task.cancel()
            logger.info(f"🛑 Stopped execution for {user_id}")


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