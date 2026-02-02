# app/core/execution_engine.py
"""
Execution Engine - The Missing Piece!

This is the continuous loop that:
1. Monitors ExecutionState per user
2. Fetches executable batches
3. Executes server tasks in parallel
4. Emits client tasks via WebSocket
5. Waits for completion and loops

✅ NEW: Event-based completion signaling for proper async waiting
"""

import asyncio
import logging
from typing import Dict, Optional, Set
from datetime import datetime

from app.core.orchestrator import get_orchestrator
from app.core.models import TaskRecord, TaskOutput
from app.core.binding_resolver import get_binding_resolver

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """
    Per-user execution engine that runs in background
    
    Each user gets their own engine instance when they send a message
    Engine lives until all tasks are complete or timeout
    
    ✅ NEW: Supports waiting for completion via events
    """
    
    def __init__(self):
        self.orchestrator = get_orchestrator()
        self.binding_resolver = get_binding_resolver()
        
        # Track running engines per user
        self.running_engines: Dict[str, asyncio.Task] = {}
        
        # ✅ NEW: Completion events for awaiting execution
        self.completion_events: Dict[str, asyncio.Event] = {}
        
        # Tool executors (will be injected)
        self.server_tool_executor = None
        self.client_task_emitter = None
        
        logger.info("✅ Execution Engine initialized")
    
    def set_server_executor(self, executor):
        """Inject server tool executor"""
        self.server_tool_executor = executor
    
    def set_client_emitter(self, emitter):
        """Inject client task emitter"""
        self.client_task_emitter = emitter
    
    async def start_execution(self, user_id: str) -> asyncio.Task:
        """
        Start execution engine for a user (non-blocking)
        
        This is called after orchestrator.register_tasks()
        Creates a background task that runs the execution loop
        
        ✅ NEW: Creates completion event for this user
        """
        # ✅ Create completion event BEFORE starting
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
        """
        ✅ NEW: Wait for execution to complete with timeout
        
        Args:
            user_id: User identifier
            timeout: Max seconds to wait (default 30)
            
        Returns:
            True if completed successfully, False if timeout
            
        Example:
            engine = get_execution_engine()
            await engine.start_execution(user_id)
            success = await engine.wait_for_completion(user_id, timeout=60)
        """
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
            
        finally:
            # Cleanup event after waiting
            if user_id in self.completion_events:
                del self.completion_events[user_id]
    
    async def _execution_loop(self, user_id: str) -> None:
        """
        Main execution loop for a user
        
        This runs continuously until all tasks are done or timeout
        
        ✅ NEW: Signals completion event when done
        """
        logger.info(f"\n{'='*70}")
        logger.info(f"🔥 EXECUTION LOOP STARTED: {user_id}")
        logger.info(f"{'='*70}\n")
        
        iteration = 0
        max_iterations = 100  # Safety limit
        no_work_count = 0
        max_idle = 5  # Exit after 5 iterations with no work
        
        try:
            while iteration < max_iterations:
                iteration += 1
                
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
                        # Check if there are still pending tasks (waiting on dependencies)
                        state = self.orchestrator.get_state(user_id)
                        if state:
                            pending = state.get_tasks_by_status("pending")
                            running = state.get_tasks_by_status("running")
                            
                            if pending or running:
                                logger.info(f"⏳ Still have {len(pending)} pending, {len(running)} running")
                                logger.info(f"⏳ Tasks still pending/running, continuing...")
                                no_work_count = 0  # Reset
                                await asyncio.sleep(1)
                                continue
                        
                        logger.info("✅ No more work - execution complete!")
                        break
                    
                    await asyncio.sleep(0.5)
                    continue
                
                # Reset idle counter
                no_work_count = 0
                
                logger.info(f"📦 Batch: {len(batch.server_tasks)} server, {len(batch.client_tasks)} client")
                
                # 2. Execute server tasks in PARALLEL
                if batch.server_tasks:
                    logger.info(f"\n🚀 Executing {len(batch.server_tasks)} server tasks in parallel...")
                    await self._execute_server_batch(user_id, batch.server_tasks)
                
                # 3. Emit client tasks (with smart batching)
                if batch.client_tasks:
                    logger.info(f"\n📤 Emitting {len(batch.client_tasks)} client tasks...")
                    await self._emit_client_batch(user_id, batch.client_tasks)
                
                # 4. Small delay before next iteration
                await asyncio.sleep(0.3)
            
            if iteration >= max_iterations:
                logger.warning(f"⚠️  Max iterations reached for {user_id}")
        
        except Exception as e:
            print(f"DEBUG: Execution loop error for {user_id}: {e}")
            logger.error(f"❌ Execution loop error for {user_id}: {e}", exc_info=True)
        
        finally:
            # Cleanup
            if user_id in self.running_engines:
                del self.running_engines[user_id]
            
            # Print final summary
            await self._print_final_summary(user_id)
            
            # ✅ NEW: Signal completion event
            if user_id in self.completion_events:
                self.completion_events[user_id].set()
                logger.info(f"📢 Completion event signaled for {user_id}")
            
            logger.info(f"\n{'='*70}")
            logger.info(f"🏁 EXECUTION LOOP ENDED: {user_id}")
            logger.info(f"{'='*70}\n")
    
    async def _execute_server_batch(self, user_id: str, tasks: list[TaskRecord]) -> None:
        """
        Execute multiple server tasks in parallel
        
        ✅ Uses REAL ServerToolExecutor (injected at startup)
        Each task calls actual tool adapters (web_search, api_call, etc.)
        """
        if not self.server_tool_executor:
            logger.error("❌ No server tool executor configured!")
            return
        
        # Execute all tasks in parallel
        results = await asyncio.gather(
            *[self._execute_single_server_task(user_id, task) for task in tasks],
            return_exceptions=True
        )
        
        # Log results
        success_count = sum(1 for r in results if not isinstance(r, Exception))
        logger.info(f"✅ Completed {success_count}/{len(tasks)} server tasks")
    
    async def _execute_single_server_task(self, user_id: str, task: TaskRecord) -> None:
        """Execute a single server task"""
        try:
            # Mark as running
            await self.orchestrator.mark_task_running(user_id, task.task_id)
            
            logger.info(f"  🔄 Executing: {task.task_id} ({task.tool})")
            
            # Show lifecycle message
            if task.lifecycle_messages and task.lifecycle_messages.on_start:
                logger.info(f"     💬 {task.lifecycle_messages.on_start}")

            # Check if executor is available 
            if not self.server_tool_executor: 
                raise RuntimeError("Server tool executor not configured")    
            
            # ✅ RESOLVE INPUT BINDINGS BEFORE EXECUTION
            state = self.orchestrator.get_state(user_id)
            if not state:
                raise RuntimeError(f"No execution state for user: {user_id}")
            
            # Validate bindings can be resolved
            can_resolve, error = self.binding_resolver.validate_bindings(task, state)
            if not can_resolve:
                raise ValueError(f"Cannot resolve bindings: {error}")
            
            # Resolve inputs (static + bindings)
            resolved_inputs = self.binding_resolver.resolve_inputs(task, state)
            task.resolved_inputs = resolved_inputs
            
            logger.info(f"     📋 Resolved inputs: {list(resolved_inputs.keys())}")
            
            # Get timeout
            timeout = None
            if task.control and task.control.timeout_ms:
                timeout = task.control.timeout_ms / 1000
            
            # ✅ Execute the tool using REAL ServerToolExecutor
            # This calls the actual tool adapters (web_search, etc.)
            if timeout:
                output = await asyncio.wait_for(
                    self.server_tool_executor.execute(task),  # ← REAL executor!
                    timeout=timeout
                )
            else:
                output = await self.server_tool_executor.execute(task)  # ← REAL executor!
            
            # Mark completed
            await self.orchestrator.mark_task_completed(user_id, task.task_id, output)
            
            # Show success message
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
    
    async def _emit_client_batch(self, user_id: str, tasks: list[TaskRecord]) -> None:
        """
        Emit client tasks - orchestrator already detected chains!
        
        If orchestrator returned A→B→C, emit them together.
        Otherwise emit individually for parallel execution.
        """
        if not self.client_task_emitter:
            logger.error("❌ No client task emitter configured!")
            # MARK TASKS AS FAILED! (cascades to dependents automatically)
            for task in tasks:
                await self.orchestrator.mark_task_failed(
                    user_id,
                    task.task_id,
                    "Client task emitter not configured"
                )
            return 
        
        # Get state for binding resolution
        state = self.orchestrator.get_state(user_id)
        
        # Check if tasks form a chain (orchestrator already did the work!)
        is_chain = len(tasks) > 1 and self._is_dependency_chain(tasks)
        
        if is_chain:
            # Emit entire chain as batch
            logger.info(f"  📦 Emitting chained batch: {[t.task_id for t in tasks]}")
            
            # Resolve bindings for entire chain
            if state:
                for task in tasks:
                    try:
                        can_resolve, error = self.binding_resolver.validate_bindings(task, state)
                        if can_resolve:
                            resolved_inputs = self.binding_resolver.resolve_inputs(task, state)
                            task.resolved_inputs = resolved_inputs
                    except Exception as e:
                        logger.warning(f"     ⚠️  Could not resolve bindings for {task.task_id}: {e}")
            
            await self.client_task_emitter.emit_task_batch(user_id, tasks)
        else:
            # Emit tasks separately for parallel execution
            for task in tasks:
             try:
                # ✅ RESOLVE INPUT BINDINGS BEFORE EMITTING
                if state:
                    can_resolve, error = self.binding_resolver.validate_bindings(task, state)
                    if can_resolve:
                        resolved_inputs = self.binding_resolver.resolve_inputs(task, state)
                        task.resolved_inputs = resolved_inputs
                        logger.info(f"     📋 Resolved inputs for {task.task_id}")
                
                if task.lifecycle_messages and task.lifecycle_messages.on_start:
                    logger.info(f"     💬 {task.lifecycle_messages.on_start}")
                
                success = await self.client_task_emitter.emit_task_single(user_id, task)
                
                if success:
                    logger.info(f"  📤 Emitted: {task.task_id} ({task.tool})")
                else:
                    logger.warning(f"  ⚠️  Failed to emit: {task.task_id}")
            
             except Exception as e:
                logger.error(f"  ❌ Error emitting {task.task_id}: {e}")
    
    def _is_dependency_chain(self, tasks: list[TaskRecord]) -> bool:
        """
        Check if tasks form a dependency chain
        
        Returns True if tasks are: A → B → C (sequential dependencies)
        Returns False if they're independent: A, B, C (parallel)
        """
        if len(tasks) <= 1:
            return False
        
        # Check if each task (except first) depends on previous
        for i in range(1, len(tasks)):
            prev_id = tasks[i-1].task_id
            curr_deps = tasks[i].depends_on
            
            if prev_id not in curr_deps:
                return False  # Not a chain
        
        return True
    
    async def _print_final_summary(self, user_id: str):
        """Print execution summary at the end"""
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