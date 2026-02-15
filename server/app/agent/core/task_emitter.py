# app/agent/core/task_emitter.py
"""
Task Emitter - Environment Aware Task Routing

Routes tasks based on environment:
- Desktop: Executes locally via client_core (direct function call)
- Production: Emits via WebSocket to remote client
"""

import logging
from typing import List, Optional, Any

from app.agent.core.models import TaskRecord
from app.agent.core.orchestrator import get_orchestrator
from app.agent.client_core.main import (
    receive_tasks_from_server,
    receive_acknowledgment,
    receive_approval_request,
    get_execution_engine
)

logger = logging.getLogger(__name__)


class TaskEmitter:
    """
    Environment-aware task emitter.
    
    Routes tasks to appropriate execution target:
    - Desktop: Local execution via client_core
    - Production: Remote execution via WebSocket
    """
    
    def __init__(self):
        self.orchestrator = get_orchestrator()
        self.socket_handler = None
        
        # Read environment from config (not hardcoded!)
        from app.config import settings
        self.environment = settings.environment
        
        logger.info(f"✅ Task Emitter initialized (env={self.environment})")
    
    def set_environment(self, env: str):
        """Set environment (desktop/production)"""
        self.environment = env
        logger.info(f"🌍 Task Emitter environment set to: {env}")
        
    def set_socket_handler(self, handler: Any):
        """Set WebSocket handler for production execution"""
        self.socket_handler = handler
        logger.info("🔌 Socket handler attached to emitter")
    
    async def emit_task_single(self, user_id: str, task: TaskRecord) -> bool:
        """Emit single task based on environment"""
        try:
            # Mark as emitted on server side (common for both)
            await self.orchestrator.mark_task_emitted(user_id, task.task_id)
            
            # Serialize
            task_dict = task.model_dump(mode='json')
            task_dict = self._enrich_with_server_state(user_id, task_dict)
            
            # ROUTING LOGIC
            if self.environment == "desktop":
                # Local execution via client_core
                logger.info(f"🖥️  Routing task {task.task_id} to local client_core")
                execution_engine = get_execution_engine()
                await receive_tasks_from_server(user_id, [task_dict])
                
                # Wait for local completion? 
                # Ideally yes for synchronous feel in desktop
                # But execution engine runs in background task
                return True
                
            else:
                # Production WebSocket execution
                if self.socket_handler:
                    return await self.socket_handler.emit_task_single(user_id, task)
                else:
                    logger.warning("⚠️ Socket handler not set in production mode")
                    return False
            
        except Exception as e:
            logger.error(f"❌ Failed to emit task {task.task_id}: {e}")
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
            if self.environment == "desktop":
                # Serialize
                task_dicts = [task.model_dump(mode='json') for task in tasks]
                task_dicts = [self._enrich_with_server_state(user_id, td) for td in task_dicts]
                
                # Local execution
                logger.info(f"🖥️  Routing batch of {len(tasks)} tasks to local client_core")
                await receive_tasks_from_server(user_id, task_dicts)
                return True
                
            else:
                # Production WebSocket execution
                if self.socket_handler:
                    return await self.socket_handler.emit_task_batch(user_id, tasks)
                else:
                    logger.warning("⚠️ Socket handler not set in production mode")
                    return False
            
        except Exception as e:
            logger.error(f"❌ Failed to emit batch: {e}")
            return False

    async def emit_acknowledgment(self, user_id: str, message: str) -> bool:
        """Emit SQH acknowledgment (past tense confirmation)"""
        try:
            if self.environment == "desktop":
                logger.info(f"🖥️  Routing acknowledgment to local client_core: {message[:50]}...")
                await receive_acknowledgment(user_id, message)
                return True
            else:
                if self.socket_handler:
                    return await self.socket_handler.emit_acknowledgment(user_id, message)
                else:
                    return False
        except Exception as e:
            logger.error(f"❌ Failed to emit acknowledgment: {e}")
            return False

    async def request_approval(self, user_id: str, task_id: str, question: str) -> bool:
        """Request user approval for a task"""
        try:
            if self.environment == "desktop":
                logger.info(f"🖥️  Routing approval request to local client_core: {question}")
                await receive_approval_request(user_id, task_id, question)
                return True
            else:
                if self.socket_handler:
                    return await self.socket_handler.request_approval(user_id, task_id, question)
                else:
                    return False
        except Exception as e:
            logger.error(f"❌ Failed to request approval: {e}")
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