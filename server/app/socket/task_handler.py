# app/socket/task_handler.py
"""
WebSocket Task Handler - Real Production Version

Emits FULL TaskRecord to client for maximum flexibility
Client gets same data access as server orchestrator
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional, Tuple
import socketio

from app.agent.execution_gateway import get_orchestrator, TaskOutput, TaskRecord
from app.services import get_tool_output_delivery_service

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
        # Pending approval waits keyed by (user_id, task_id)
        self._pending_approvals: Dict[Tuple[str, str], asyncio.Future[bool]] = {}
    
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

    async def request_approval(self, user_id: str, task_id: str, question: str) -> bool:
        """
        Ask remote client for approval and wait for response.
        """
        if user_id not in self.connected_users or not self.connected_users[user_id]:
            logger.warning("⚠️ User %s not connected - cannot request approval for %s", user_id, task_id)
            return False

        key = (user_id, task_id)
        if key in self._pending_approvals:
            logger.warning("⚠️ Duplicate approval request ignored for %s/%s", user_id, task_id)
            return False

        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._pending_approvals[key] = future

        payload = {
            "user_id": user_id,
            "task_id": task_id,
            "question": question,
        }

        try:
            for sid in self.connected_users[user_id]:
                await self.sio.emit("task:approval:request", payload, room=sid)
            logger.info("📨 Approval requested for %s/%s", user_id, task_id)

            approved = await asyncio.wait_for(future, timeout=120.0)
            return approved
        except asyncio.TimeoutError:
            logger.warning("⏱️ Approval timeout for %s/%s", user_id, task_id)
            return False
        finally:
            self._pending_approvals.pop(key, None)

    async def resolve_approval(self, user_id: str, task_id: str, approved: bool) -> bool:
        """
        Resolve a pending approval request from client response.
        """
        key = (user_id, task_id)
        future = self._pending_approvals.get(key)
        if not future:
            logger.warning("⚠️ Approval response with no pending request: %s/%s", user_id, task_id)
            return False
        if future.done():
            return False
        future.set_result(approved)
        return True


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

    @sio.on("task:approval:response")  # type: ignore
    async def handle_approval_response(sid: str, data: Dict[str, Any]):
        """
        Client responds to approval request.
        """
        try:
            if not isinstance(data, dict):
                data = {}
            session = await sio.get_session(sid)
            session_user = session.get("user_id")
            if not session_user:
                return

            user_id = data.get("user_id") or session_user
            if user_id != session_user:
                logger.warning("⚠️ Approval response user mismatch: sid_user=%s payload_user=%s", session_user, user_id)
                return

            task_id = data.get("task_id")
            if not task_id:
                return

            approved_raw = data.get("approved", False)
            if isinstance(approved_raw, bool):
                approved = approved_raw
            else:
                approved = str(approved_raw).strip().lower() in {"1", "true", "yes", "approve", "approved"}

            resolved = await handler.resolve_approval(user_id, task_id, approved)
            await sio.emit(
                "task:approval:ack",
                {"task_id": task_id, "resolved": resolved, "approved": approved},
                to=sid,
            )
        except Exception as e:
            logger.error(f"Error handling approval response: {e}", exc_info=True)

    @sio.on("tool:output:get")  # type: ignore
    async def handle_tool_output_get(sid: str, data: Dict[str, Any]):
        """
        On-demand output fetch for completed tasks.
        Keeps large tool payloads off the default live stream path.
        """
        try:
            if not isinstance(data, dict):
                data = {}
            session = await sio.get_session(sid)
            session_user = session.get("user_id")
            if not session_user:
                return

            user_id = data.get("user_id") or session_user
            if user_id != session_user:
                logger.warning("⚠️ tool:output:get user mismatch: sid_user=%s payload_user=%s", session_user, user_id)
                await sio.emit("tool:output", {"success": False, "error": "Unauthorized user_id"}, to=sid)
                return

            task_id = data.get("task_id")
            tool_name = data.get("tool_name")
            include_full = bool(data.get("include_full", False))
            raw_fields = data.get("fields")
            fields: Optional[List[str]] = raw_fields if isinstance(raw_fields, list) else None

            payload = await get_tool_output_delivery_service().get_output(
                user_id=user_id,
                task_id=task_id,
                tool_name=tool_name,
                include_full=include_full,
                fields=fields,
            )
            if not payload:
                await sio.emit("tool:output", {"success": False, "error": "No matching task output found"}, to=sid)
                return

            await sio.emit("tool:output", {"success": True, "output": payload}, to=sid)
        except Exception as e:
            logger.error(f"Error handling tool:output:get: {e}", exc_info=True)
            await sio.emit("tool:output", {"success": False, "error": str(e)}, to=sid)

    @sio.on("tool:output:list")  # type: ignore
    async def handle_tool_output_list(sid: str, data: Dict[str, Any]):
        """
        List recent completed tool outputs (metadata only).
        """
        try:
            if not isinstance(data, dict):
                data = {}
            session = await sio.get_session(sid)
            session_user = session.get("user_id")
            if not session_user:
                return

            user_id = data.get("user_id") or session_user
            if user_id != session_user:
                await sio.emit("tool:outputs", {"success": False, "error": "Unauthorized user_id"}, to=sid)
                return

            limit_raw = data.get("limit", 10)
            try:
                limit = max(1, min(50, int(limit_raw)))
            except Exception:
                limit = 10

            outputs = await get_tool_output_delivery_service().list_outputs(user_id=user_id, limit=limit)
            await sio.emit("tool:outputs", {"success": True, "outputs": outputs}, to=sid)
        except Exception as e:
            logger.error(f"Error handling tool:output:list: {e}", exc_info=True)
            await sio.emit("tool:outputs", {"success": False, "error": str(e)}, to=sid)
    
    logger.info("✅ Task event handlers registered")
    return handler


def get_task_handler(
    sio: socketio.AsyncServer, 
    connected_users: Dict[str, set]
) -> SocketTaskHandler:
    """Factory function to create task handler"""
    return SocketTaskHandler(sio, connected_users)

