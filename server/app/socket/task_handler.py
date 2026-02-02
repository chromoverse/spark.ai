# app/socket/task_handler.py
"""
WebSocket Task Handler - Real Production Version

Emits FULL TaskRecord to client for maximum flexibility
Client gets same data access as server orchestrator
"""

import logging
from typing import Dict, Any, List
import socketio

from app.core.orchestrator import get_orchestrator
from app.core.models import TaskOutput, TaskRecord

logger = logging.getLogger(__name__)


class SocketTaskHandler:
    """
    Production WebSocket task handler
    
    Emits complete TaskRecord to client - client orchestrator 
    has same level of access as server orchestrator
    
    ✅ Always sends tasks as array with user_id (consistent interface)
    ✅ Enriches with server-side dependency completion info
    """
    
    def __init__(self, sio: socketio.AsyncServer, connected_users: Dict[str, set]):
        self.sio = sio
        self.connected_users = connected_users
        self.orchestrator = get_orchestrator()
    
    async def emit_task_single(self, user_id: str, task: TaskRecord) -> bool:
        """
        Emit single task to client
        
        ✅ Always sends as array with user_id for consistent interface
        ✅ Enriches with server-side dependency completion info
        """
        # Check if user is connected
        if user_id not in self.connected_users or not self.connected_users[user_id]:
            logger.warning(f"⚠️  User {user_id} not connected - cannot emit task {task.task_id}")
            return False
        
        # Get one of the user's socket IDs
        sid = next(iter(self.connected_users[user_id]))
        
        try:
            # Serialize to JSON dict
            task_dict = task.model_dump(mode='json')
            
            # ✅ Enrich with server-side dependency state
            task_dict = self._enrich_with_server_state(user_id, task_dict)
            
            # ✅ Always send as array with user_id
            payload = {
                "user_id": user_id,
                "tasks": [task_dict]  # Single task in array
            }
            
            # Emit to client
            await self.sio.emit(
                "task:execute",
                payload,
                room=sid
            )
            
            # Mark as emitted
            await self.orchestrator.mark_task_emitted(user_id, task.task_id)
            
            logger.info(f"📤 Emitted task {task.task_id} to client {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to emit task {task.task_id}: {e}")
            return False
    
    async def emit_task_batch(self, user_id: str, tasks: List[TaskRecord]) -> bool:
        """
        Emit batch of tasks to client (for chains)
        
        ✅ Client receives entire chain and handles dependencies locally
        ✅ Enriches each task with server-side dependency state
        This is MUCH faster than individual emissions!
        """
        # Check if user is connected
        if user_id not in self.connected_users or not self.connected_users[user_id]:
            logger.warning(f"⚠️  User {user_id} not connected - cannot emit batch")
            return False
        
        sid = next(iter(self.connected_users[user_id]))
        
        try:
            # Serialize all to JSON dicts
            task_dicts = [task.model_dump(mode='json') for task in tasks]
            
            # ✅ Enrich with server-side dependency state
            task_dicts = [self._enrich_with_server_state(user_id, td) for td in task_dicts]
            
            # ✅ Send as array with user_id (consistent interface)
            payload = {
                "user_id": user_id,
                "tasks": task_dicts
            }
            
            # Emit to client
            await self.sio.emit(
                "task:execute_batch",
                payload,
                room=sid
            )
            
            # Mark all as emitted
            for task in tasks:
                await self.orchestrator.mark_task_emitted(user_id, task.task_id)
            
            logger.info(f"📦 Emitted batch of {len(tasks)} tasks to client {user_id}")
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
            Enriched task dictionary with 'server_completed_dependencies' field
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
    
    async def handle_task_result(
        self, 
        user_id: str, 
        task_id: str, 
        result: Dict[str, Any]
    ) -> None:
        """
        Handle task result acknowledgment from client
        
        Client sends back TaskOutput after execution
        """
        try:
            # Parse result into TaskOutput
            output = TaskOutput(
                success=result.get("success", False),
                data=result.get("data", {}),
                error=result.get("error")
            )
            
            # Update orchestrator (no lock needed - called from socket handler)
            await self.orchestrator.handle_client_ack(user_id, task_id, output)
            
            logger.info(f"✅ Received result for task {task_id} from {user_id}")
            
        except Exception as e:
            logger.error(f"❌ Failed to handle task result: {e}")
            await self.orchestrator.mark_task_failed(
                user_id, 
                task_id, 
                f"Failed to process client result: {str(e)}"
            )
    
    async def notify_task_status(
        self, 
        user_id: str, 
        task_id: str, 
        status: str
    ) -> None:
        """
        Notify client about task status change
        (Optional - for real-time UI updates)
        """
        if user_id not in self.connected_users:
            return
        
        payload = {
            "task_id": task_id,
            "status": status
        }
        
        # Emit to all user's connections
        for sid in self.connected_users[user_id]:
            try:
                await self.sio.emit(
                    "task:status",
                    payload,
                    room=sid
                )
            except Exception as e:
                logger.error(f"Failed to notify status: {e}")


# Socket.IO event registration
async def register_task_events(
    sio: socketio.AsyncServer, 
    connected_users: Dict[str, set]
) -> SocketTaskHandler:
    """
    Register task-related WebSocket events
    
    Returns handler for injection into execution engine
    """
    handler = SocketTaskHandler(sio, connected_users)
    
    @sio.on("task:result") #type: ignore
    async def handle_task_result(sid: str, data: Dict[str, Any]):
        """
        Client sends task execution result
        
        Expected data:
        {
            "user_id": "user_123",
            "task_id": "task_abc",
            "result": {
                "success": true,
                "data": {...},
                "error": null
            }
        }
        """
        try:
            user_id = data.get("user_id")
            task_id = data.get("task_id")
            result = data.get("result", {})
            
            if not user_id or not task_id:
                logger.error("Missing user_id or task_id in task result")
                return
            
            await handler.handle_task_result(user_id, task_id, result)
            
        except Exception as e:
            logger.error(f"Error handling task result: {e}")
    
    @sio.on("task:batch_results") #type: ignore
    async def handle_batch_results(sid: str, data: Dict[str, Any]):
        """
        Client sends results for entire batch
        
        Expected data:
        {
            "user_id": "user_123",
            "results": [
                {"task_id": "task_1", "result": {...}},
                {"task_id": "task_2", "result": {...}}
            ]
        }
        """
        try:
            user_id = data.get("user_id")
            results = data.get("results", [])
            
            for item in results:
                task_id = item.get("task_id")
                result = item.get("result", {})
                
                if task_id:
                    await handler.handle_task_result(user_id, task_id, result) #type: ignore
            
            logger.info(f"✅ Processed {len(results)} batch results from {user_id}")
            
        except Exception as e:
            logger.error(f"Error handling batch results: {e}")
    
    logger.info("✅ Task event handlers registered")
    return handler


def get_task_handler(
    sio: socketio.AsyncServer, 
    connected_users: Dict[str, set]
) -> SocketTaskHandler:
    """Factory function to create task handler"""
    return SocketTaskHandler(sio, connected_users)