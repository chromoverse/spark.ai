# app/kernel/task_emitter.py
"""
Task Emitter - Environment Aware Task Routing.

Desktop mode uses in-process execution in the unified kernel execution engine.
Production mode emits tasks to connected remote clients over WebSocket.
"""

import asyncio
import logging
from typing import List, Optional, Any

from app.kernel.execution.execution_models import TaskRecord
from app.kernel.execution.orchestrator import get_orchestrator

logger = logging.getLogger(__name__)


class TaskEmitter:
    """
    Environment-aware task emitter.
    
    Routes tasks to appropriate execution target:
    - Desktop: Local execution by kernel execution engine (no remote emit)
    - Production: Remote execution via WebSocket
    """
    
    def __init__(self):
        self.orchestrator = get_orchestrator()
        self.socket_handler = None
        
        # Read environment from config (not hardcoded!)
        from app.config import settings
        self.environment = settings.environment
        
        logger.info(f"Task Emitter initialized (env={self.environment})")
    
    def set_environment(self, env: str):
        """Set environment (desktop/production)"""
        self.environment = str(env or "").strip().upper()
        logger.info("Task Emitter environment set to: %s", self.environment)
        
    def set_socket_handler(self, handler: Any):
        """Set WebSocket handler for production execution"""
        self.socket_handler = handler
        logger.info("Socket handler attached to emitter")
    
    async def emit_task_single(self, user_id: str, task: TaskRecord) -> bool:
        """Emit single task based on environment"""
        try:
            # Mark as emitted on server side (common for both)
            await self.orchestrator.mark_task_emitted(user_id, task.task_id)
            
            # Serialize
            task_dict = task.model_dump(mode='json')
            task_dict = self._enrich_with_server_state(user_id, task_dict)
            
            # ROUTING LOGIC
            if self.environment == "DESKTOP":
                # Desktop execution is already handled inside kernel execution engine.
                logger.info("Desktop mode: task %s handled in-process by kernel engine", task.task_id)
                return True
                
            else:
                # Production WebSocket execution
                if self.socket_handler:
                    return await self.socket_handler.emit_task_single(user_id, task)
                else:
                    logger.warning("Socket handler not set in production mode")
                    return False
            
        except Exception as e:
            logger.error(f"Failed to emit task {task.task_id}: {e}")
            return False
    
    async def emit_task_batch(self, user_id: str, tasks: List[TaskRecord]) -> bool:
        """Emit batch based on environment"""
        if not tasks:
            return True
            
        try:
            # Mark all as emitted
            for task in tasks:
                await self.orchestrator.mark_task_emitted(user_id, task.task_id)
            
            # ROUTING LOGIC
            if self.environment == "DESKTOP":
                logger.info("Desktop mode: batch of %s tasks handled in-process by kernel engine", len(tasks))
                return True
                
            else:
                # Production WebSocket execution
                if self.socket_handler:
                    return await self.socket_handler.emit_task_batch(user_id, tasks)
                else:
                    logger.warning("Socket handler not set in production mode")
                    return False
            
        except Exception as e:
            logger.error(f"Failed to emit batch: {e}")
            return False

    async def emit_acknowledgment(self, user_id: str, message: str) -> bool:
        """Emit SQH acknowledgment (past tense confirmation)"""
        try:
            if self.environment == "DESKTOP":
                logger.info("Desktop mode acknowledgment for %s: %s", user_id, message[:50])
                from app.agent.desktop_notifications import show_info_notification

                show_info_notification("SPARK AI", message)
                return True
            else:
                if self.socket_handler:
                    return await self.socket_handler.emit_acknowledgment(user_id, message)
                else:
                    return False
        except Exception as e:
            logger.error(f"Failed to emit acknowledgment: {e}")
            return False

    async def request_approval(self, user_id: str, task_id: str, question: str) -> bool:
        """Request user approval for a task"""
        try:
            if self.environment == "DESKTOP":
                logger.info("Desktop mode approval request for task %s", task_id)
                loop = asyncio.get_running_loop()
                decision: asyncio.Future[bool] = loop.create_future()

                async def _handle_response(uid: str, tid: str, approved: bool) -> None:
                    await self.orchestrator.handle_approval(uid, tid, approved)
                    if not decision.done():
                        loop.call_soon_threadsafe(decision.set_result, approved)

                from app.agent.desktop_notifications import show_approval_notification

                show_approval_notification(
                    user_id=user_id,
                    task_id=task_id,
                    question=question,
                    on_response_callback=_handle_response,
                )
                try:
                    return await asyncio.wait_for(decision, timeout=120.0)
                except asyncio.TimeoutError:
                    logger.warning("⏱️ Desktop approval timeout for %s/%s", user_id, task_id)
                    task = self.orchestrator.get_task(user_id, task_id)
                    if task and task.status == "waiting":
                        await self.orchestrator.handle_approval(user_id, task_id, False)
                    return False
            else:
                if self.socket_handler:
                    return await self.socket_handler.request_approval(user_id, task_id, question)
                else:
                    return False
        except Exception as e:
            logger.error(f"Failed to request approval: {e}")
            return False
    
    def _enrich_with_server_state(self, user_id: str, task_dict: dict) -> dict:
        """Enrich task dict with server-side dependency completion info"""
        state = self.orchestrator.get_state(user_id)
        if not state:
            return task_dict
        
        depends_on = task_dict.get('task', {}).get('depends_on', [])
        if not depends_on:
            return task_dict
        
        completed_deps = []
        for dep_id in depends_on:
            dep_task = state.get_task(dep_id)
            if dep_task and dep_task.status == "completed":
                completed_deps.append(dep_id)
        
        if completed_deps:
            task_dict['server_completed_dependencies'] = completed_deps
        
        return task_dict


# Global singleton
_task_emitter: Optional[TaskEmitter] = None


def get_task_emitter() -> TaskEmitter:
    """Get global task emitter instance"""
    global _task_emitter
    if _task_emitter is None:
        _task_emitter = TaskEmitter()
    return _task_emitter


def init_task_emitter() -> TaskEmitter:
    """Initialize task emitter at startup"""
    global _task_emitter
    _task_emitter = TaskEmitter()
    return _task_emitter


