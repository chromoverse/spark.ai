# client_core/engine/execution_engine.py
"""
Client-Side Execution Engine

Executes tasks locally on client.
"""

import asyncio
import logging
from typing import Optional, List, Dict, Any

from .orchestrator import ClientOrchestrator
from .binding_resolver import ClientBindingResolver
from ..models import TaskRecord, TaskOutput

logger = logging.getLogger(__name__)


class ClientExecutionEngine:
    """
    Client-side execution engine.
    
    Receives tasks from server and executes them locally.
    """
    
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.orchestrator = ClientOrchestrator(user_id)
        self.resolver = ClientBindingResolver()
        self.tool_executor = None  # Injected
        
        self.running = False
        self.execution_task: Optional[asyncio.Task] = None
        
        logger.info(f"✅ Client Execution Engine initialized for {user_id}")
    
    def set_tool_executor(self, executor):
        """Inject client tool executor."""
        self.tool_executor = executor
    
    async def receive_tasks(self, task_records: List[Dict[str, Any]]) -> None:
        """
        Receive task records from server.
        
        Args:
            task_records: List of TaskRecord dicts
        """
        if not task_records:
            logger.warning("⚠️  Received empty task list")
            return
        
        logger.info(f"📥 Received {len(task_records)} task(s) from server")
        
        # Register all tasks
        self.orchestrator.register_batch(task_records)
        
        # Start execution if not running
        if not self.running:
            await self.start()
    
    async def receive_task(self, task) -> None:
        """Receive a single Task object (convenience method)."""
        if hasattr(task, '__dict__'):
            task_dict = {
                "task_id": task.task_id,
                "tool": task.tool,
                "execution_target": task.execution_target,
                "depends_on": task.depends_on,
                "inputs": task.inputs,
                "input_bindings": task.input_bindings,
                "lifecycle_messages": task.lifecycle_messages,
                "control": getattr(task, 'control', None)
            }
        else:
            task_dict = task
        
        task_record = {
            "task": task_dict,
            "status": "pending",
            "resolved_inputs": {}
        }
        await self.receive_tasks([task_record])
    
    async def receive_batch(self, tasks_data: List[Dict[str, Any]]) -> None:
        """Receive batch as list of task dicts."""
        task_records = []
        for task_dict in tasks_data:
            task_records.append({
                "task": task_dict,
                "status": "pending",
                "resolved_inputs": task_dict.get("resolved_inputs", {})
            })
        await self.receive_tasks(task_records)
    
    async def start(self) -> None:
        """Start execution loop."""
        if self.running:
            logger.warning("⚠️  Execution already running")
            return
        
        self.running = True
        self.execution_task = asyncio.create_task(self._execution_loop())
        logger.info("🚀 Client execution started")
    
    async def stop(self) -> None:
        """Stop execution loop."""
        if self.execution_task:
            self.execution_task.cancel()
            self.running = False
            logger.info("🛑 Client execution stopped")
    
    async def wait_for_completion(self) -> None:
        """Wait for all tasks to complete."""
        if self.execution_task:
            await self.execution_task
    
    async def _execution_loop(self) -> None:
        """Main execution loop."""
        logger.info("\n" + "="*60)
        logger.info("🔥 CLIENT EXECUTION STARTED")
        logger.info("="*60 + "\n")
        
        iteration = 0
        max_iterations = 50
        no_work_count = 0
        
        try:
            while iteration < max_iterations and self.running:
                iteration += 1
                
                logger.info(f"\n{'─'*60}")
                logger.info(f"Iteration {iteration}")
                logger.info(f"{'─'*60}")
                
                executable = self.orchestrator.get_executable_tasks()
                
                if not executable:
                    no_work_count += 1
                    logger.info("⏸️  No executable tasks")
                    
                    if no_work_count >= 3:
                        summary = self.orchestrator.get_summary()
                        if summary['pending'] == 0 and summary['running'] == 0:
                            logger.info("✅ All tasks complete!")
                            break
                    
                    await asyncio.sleep(0.1)
                    continue
                
                no_work_count = 0
                logger.info(f"📦 Found {len(executable)} executable tasks")
                
                await asyncio.gather(
                    *[self._execute_task(task) for task in executable],
                    return_exceptions=True
                )
                
                await asyncio.sleep(0.1)
            
            if iteration >= max_iterations:
                logger.warning("⚠️  Max iterations reached")
        
        # except Exception as e:
        #     logger.error(f"❌ Execution loop error: {e}")
        
        finally:
            self.running = False
            self._print_summary()
            
            logger.info("\n" + "="*60)
            logger.info("🏁 CLIENT EXECUTION COMPLETE")
            logger.info("="*60 + "\n")
    
    async def _execute_task(self, task: TaskRecord) -> None:
        """Execute a single task locally."""
        try:
            self.orchestrator.mark_task_running(task.task_id)
            
            logger.info(f"  🔄 Executing: {task.task_id} ({task.tool})")
            #TODO : [IPC] Send 'task_started' update to host process via IPC/WebSocket
            # await send_ipc_update("task_started", { "task_id": task.task_id })
            
            if task.task.lifecycle_messages:
                msg = task.task.lifecycle_messages.on_start
                if msg:
                    logger.info(f"     💬 {msg}")
            
            resolved_inputs = self.resolver.resolve_inputs(
                task, 
                self.orchestrator.state
            )
            
            logger.info(f"     📋 Resolved inputs: {list(resolved_inputs.keys())}")
            
            if not self.tool_executor:
                raise RuntimeError("Tool executor not configured")
            
            output = await self.tool_executor.execute(task, resolved_inputs)
            
            self.orchestrator.mark_task_completed(task.task_id, output)
            
            # TODO: [IPC] Send 'task_completed' update to host process via IPC/WebSocket
            # await send_ipc_update("task_completed", { "task_id": task.task_id, "output": output.dict() })
            
            if task.task.lifecycle_messages:
                msg = task.task.lifecycle_messages.on_success
                if msg:
                    logger.info(f"     💬 {msg}")
            
            logger.info(f"  ✅ Completed: {task.task_id}")
        
        except Exception as e:
            error = str(e)
            self.orchestrator.mark_task_failed(task.task_id, error)
            
            # TODO: [IPC] Send 'task_failed' update to host process via IPC/WebSocket
            # await send_ipc_update("task_failed", { "task_id": task.task_id, "error": error })
            
            if task.task.lifecycle_messages:
                msg = task.task.lifecycle_messages.on_failure
                if msg:
                    logger.info(f"     💬 {msg}")
            
            logger.error(f"  ❌ Failed: {task.task_id} - {error}")
    
    def _print_summary(self):
        """Print execution summary."""
        summary = self.orchestrator.get_summary()
        
        logger.info("\n" + "="*60)
        logger.info("CLIENT EXECUTION SUMMARY")
        logger.info("="*60)
        logger.info(f"Total:     {summary['total']}")
        logger.info(f"✅ Done:   {summary['completed']}")
        logger.info(f"❌ Failed: {summary['failed']}")
        logger.info(f"⏳ Pending: {summary['pending']}")
        logger.info("="*60)


# Global singleton
_client_engine: Optional[ClientExecutionEngine] = None


def get_client_engine() -> Optional[ClientExecutionEngine]:
    """Get global client engine instance."""
    return _client_engine


def init_client_engine(user_id: str) -> ClientExecutionEngine:
    """Initialize client engine."""
    global _client_engine
    _client_engine = ClientExecutionEngine(user_id)
    return _client_engine
