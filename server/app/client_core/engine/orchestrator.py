# client_core/engine/orchestrator.py
"""
Client-Side Task Orchestrator

Manages client-side task execution state.
"""

import logging
from typing import Optional, List, Dict, Any, Set
from datetime import datetime

from ..models import (
    Task, TaskRecord, ExecutionState,
    TaskOutput, TaskStatus
)

logger = logging.getLogger(__name__)


class ClientOrchestrator:
    """
    Client-side orchestrator.
    
    Responsibilities:
    - Store received tasks from server
    - Track execution state
    - Provide task outputs for binding resolution
    - Track server-completed dependencies
    """
    
    def __init__(self, user_id: str):
        self.state = ExecutionState(user_id=user_id)
        # Track dependencies completed on server (not visible to client)
        self.server_completed_dependencies: Set[str] = set()
        logger.info(f"✅ Client Orchestrator initialized for {user_id}")
    
    def register_task(self, task_record_data: Dict[str, Any]) -> TaskRecord:
        """
        Register task received from server.
        
        Args:
            task_record_data: TaskRecord data from server (dict)
            
        Returns:
            TaskRecord
        """
        # Extract server-completed dependencies metadata
        server_completed = task_record_data.pop('server_completed_dependencies', [])
        if server_completed:
            self.server_completed_dependencies.update(server_completed)
            logger.info(f"   📊 Marking {len(server_completed)} dependencies as server-completed: {server_completed}")
        
        record = TaskRecord.model_validate(task_record_data)
        record.status = "pending"
        self.state.add_task(record)
        logger.info(f"📥 Registered task: {record.task_id} ({record.tool})")
        return record
    
    def register_batch(self, tasks_data: List[Dict[str, Any]]) -> List[TaskRecord]:
        """
        Register batch of tasks from server.
        """
        records = []
        for task_data in tasks_data:
            record = self.register_task(task_data)
            records.append(record)
        
        logger.info(f"📦 Registered batch of {len(records)} tasks")
        return records
    
    def mark_task_running(self, task_id: str) -> None:
        """Mark task as running."""
        task = self.state.get_task(task_id)
        if task:
            task.status = "running"
            task.started_at = datetime.now()
            logger.info(f"🔄 Task {task_id} started")
    
    def mark_task_completed(self, task_id: str, output: TaskOutput) -> None:
        """Mark task as completed with output."""
        task = self.state.get_task(task_id)
        if task:
            task.status = "completed"
            task.output = output
            task.completed_at = datetime.now()
            
            if task.started_at:
                duration = (task.completed_at - task.started_at).total_seconds() * 1000
                task.duration_ms = int(duration)
            
            logger.info(f"✅ Task {task_id} completed ({task.duration_ms}ms)")
    
    def mark_task_failed(self, task_id: str, error: str) -> None:
        """Mark task as failed."""
        task = self.state.get_task(task_id)
        if task:
            task.status = "failed"
            task.error = error
            task.completed_at = datetime.now()
            
            if task.started_at:
                duration = (task.completed_at - task.started_at).total_seconds() * 1000
                task.duration_ms = int(duration)
            
            logger.error(f"❌ Task {task_id} failed: {error}")
    
    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        """Get task by ID."""
        return self.state.get_task(task_id)
    
    def get_executable_tasks(self) -> List[TaskRecord]:
        """
        Get tasks ready to execute.
        
        Returns tasks whose dependencies are completed.
        Now considers both:
        - Client-side completed tasks
        - Server-side completed tasks (tracked separately)
        """
        executable = []
        pending_tasks = [
            task for task in self.state.tasks.values()
            if task.status == "pending"
        ]
        
        # Combine client-completed + server-completed dependencies
        completed_ids = self.state.get_completed_task_ids()
        all_completed = set(completed_ids).union(self.server_completed_dependencies)
        
        for task in pending_tasks:
            # Check if all dependencies are satisfied
            # (either completed on client OR completed on server)
            if all(dep_id in all_completed for dep_id in task.depends_on):
                executable.append(task)
                if task.depends_on:
                    # Log which deps were server vs client
                    server_deps = [d for d in task.depends_on if d in self.server_completed_dependencies]
                    client_deps = [d for d in task.depends_on if d in completed_ids]
                    logger.info(f"   ✅ Task {task.task_id} ready (server deps: {server_deps}, client deps: {client_deps})")
        
        return executable
    
    def get_summary(self) -> dict:
        """Get execution summary."""
        summary = {
            "total": len(self.state.tasks),
            "pending": 0,
            "running": 0,
            "completed": 0,
            "failed": 0
        }
        
        for task in self.state.tasks.values():
            summary[task.status] += 1
        
        return summary