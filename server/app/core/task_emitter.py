# app/core/task_emitter.py
"""
Task Emitter - Fake WebSocket for Development

Emits tasks directly to client_core_demo instead of via WebSocket.
Acts as a drop-in replacement for SocketTaskHandler during development.
"""

import logging
from typing import List, Callable, Awaitable, Optional

from app.core.models import TaskRecord
from app.core.orchestrator import get_orchestrator
from app.client_core.main import receive_tasks_from_server, get_execution_engine

logger = logging.getLogger(__name__)


# Type for the callback function
TaskCallback = Callable[[str, List[dict]], Awaitable[None]]


class TaskEmitter:
    """
    Fake WebSocket task emitter for development.
    
    Instead of sending tasks over WebSocket, directly calls
    client_core_demo.main.receive_tasks_from_server().
    
    Implements same interface as SocketTaskHandler for seamless swapping:
    - emit_task_single(user_id, task) -> bool
    - emit_task_batch(user_id, tasks) -> bool
    """
    
    def __init__(self):
        self.orchestrator = get_orchestrator()
        self._client_callback: Optional[TaskCallback] = None
        
        logger.info("✅ Task Emitter initialized (fake WebSocket mode)")
    
    def set_client_callback(self, callback: TaskCallback) -> None:
        """
        Set the callback function to receive tasks.
        
        Args:
            callback: Async function with signature:
                      async def callback(user_id: str, tasks: List[dict]) -> None
        """
        self._client_callback = callback
        logger.info("✅ Client callback registered")
    
    async def emit_task_single(self, user_id: str, task: TaskRecord) -> bool:
        """
        Emit single task to client.
        
        Serializes TaskRecord to JSON dict and calls client callback.
        Always sends as list for consistent interface.
        
        Args:
            user_id: User ID
            task: TaskRecord to emit
            
        Returns:
            True if emission successful
        """
        try:
            # Mark as emitted on server side
            await self.orchestrator.mark_task_emitted(user_id, task.task_id)
            
            # Serialize to JSON dict (like WebSocket would do)
            task_dict = task.model_dump(mode='json')
            
            # ✅ ADD: Include completed server dependencies
            task_dict = self._enrich_with_server_state(user_id, task_dict)
            
            # Send to client as list (consistent interface)
            execution_engine = get_execution_engine()
            await receive_tasks_from_server(user_id, [task_dict])
            await execution_engine.wait_for_completion()
            
            logger.info(f"📤 Emitted task {task.task_id} to client")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to emit task {task.task_id}: {e}")
            return False
    
    async def emit_task_batch(self, user_id: str, tasks: List[TaskRecord]) -> bool:
        """
        Emit batch of tasks to client.
        
        Serializes all TaskRecords to JSON dicts and calls client callback.
        
        Args:
            user_id: User ID
            tasks: List of TaskRecords to emit
            
        Returns:
            True if emission successful
        """
        try:
            # Mark all as emitted on server side
            for task in tasks:
                await self.orchestrator.mark_task_emitted(user_id, task.task_id)
            
            # Serialize all to JSON dicts
            task_dicts = [task.model_dump(mode='json') for task in tasks]
            
            # ✅ ADD: Enrich with server-side dependency state
            task_dicts = [self._enrich_with_server_state(user_id, td) for td in task_dicts]
            
            # Send entire batch to client
            execution_engine = get_execution_engine()
            await receive_tasks_from_server(user_id, task_dicts)
            await execution_engine.wait_for_completion()
            
            logger.info(f"📦 Emitted batch of {len(tasks)} tasks to client")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to emit batch: {e}")
            return False
    
    def _enrich_with_server_state(self, user_id: str, task_dict: dict) -> dict:
        """
        Enrich task dict with server-side dependency completion info.
        
        For tasks being sent to client, we need to include info about
        which dependencies were already completed on the server side.
        
        Args:
            user_id: User ID
            task_dict: Task dictionary to enrich
            
        Returns:
            Enriched task dictionary with 'completed_dependencies' field
        """
        state = self.orchestrator.get_state(user_id)
        if not state:
            return task_dict
        
        # Get the task's dependencies
        depends_on = task_dict.get('task', {}).get('depends_on', [])
        if not depends_on:
            return task_dict
        
        # Check which dependencies are completed on server
        completed_deps = []
        for dep_id in depends_on:
            dep_task = state.get_task(dep_id)
            if dep_task and dep_task.status == "completed":
                completed_deps.append(dep_id)
        
        # Add metadata about completed dependencies
        if completed_deps:
            task_dict['server_completed_dependencies'] = completed_deps
            logger.info(f"   📊 Task {task_dict.get('task_id')} has {len(completed_deps)} server-completed deps: {completed_deps}")
        
        return task_dict


# Global singleton
_task_emitter: Optional[TaskEmitter] = None


def get_task_emitter() -> TaskEmitter:
    """Get global task emitter instance."""
    global _task_emitter
    if _task_emitter is None:
        _task_emitter = TaskEmitter()
    return _task_emitter


def init_task_emitter() -> TaskEmitter:
    """Initialize task emitter at startup."""
    global _task_emitter
    _task_emitter = TaskEmitter()
    return _task_emitter


def setup_client_demo_emitter() -> TaskEmitter:
    """
    Setup task emitter with client_core_demo callback.
    
    Convenience function to wire up the emitter with client callback.
    
    Usage:
        from app.core.task_emitter import setup_client_demo_emitter
        
        emitter = setup_client_demo_emitter()
        # Now emitter will send tasks to client_core_demo
    """
    from app.client_core.main import receive_tasks_from_server
    
    emitter = get_task_emitter()
    emitter.set_client_callback(receive_tasks_from_server)
    
    logger.info("✅ Task Emitter wired to client_core_demo")
    return emitter