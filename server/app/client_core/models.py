# client_core/models.py
"""
Models for task orchestration - Client Side

Standalone Pydantic models used by the client execution system.
"""

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field
from datetime import datetime


ExecutionTarget = Literal["client", "server"]
FailurePolicy = Literal["abort", "continue", "retry"]
TaskStatus = Literal["pending", "running", "completed", "failed", "waiting", "emitted"]


class LifecycleMessages(BaseModel):
    """Messages shown during task lifecycle"""
    on_start: Optional[str] = None
    on_success: Optional[str] = None
    on_failure: Optional[str] = None


class TaskControl(BaseModel):
    """Task execution control settings"""
    confidence: Optional[float] = None
    requires_approval: Optional[bool] = None
    approval_question: Optional[str] = None
    on_failure: FailurePolicy = "abort"
    timeout_ms: Optional[int] = None


class Task(BaseModel):
    """
    Immutable task definition from server/LLM.
    
    This is the inner task object inside TaskRecord.
    """
    task_id: str = Field(..., description="Unique task identifier")
    tool: str = Field(..., description="Tool name from tool_registry")
    execution_target: ExecutionTarget
    
    depends_on: List[str] = Field(default_factory=list, description="Task IDs this task depends on")
    
    inputs: Dict[str, Any] = Field(default_factory=dict, description="Static input values")
    
    input_bindings: Dict[str, str] = Field(
        default_factory=dict,
        description="JSONPath bindings to previous task outputs"
    )
    
    lifecycle_messages: Optional[LifecycleMessages] = None
    control: Optional[TaskControl] = None


class TaskOutput(BaseModel):
    """Standardized task execution output"""
    success: bool
    data: Dict[str, Any]
    error: Optional[str] = None


class TaskRecord(BaseModel):
    """
    Mutable task execution record.
    
    Contains the full Task plus execution state.
    """
    task: Task = Field(..., description="Complete task definition from LLM")
    
    # Execution state (mutable)
    status: TaskStatus = "pending"
    resolved_inputs: Dict[str, Any] = Field(default_factory=dict, description="Inputs after binding resolution")
    output: Optional[TaskOutput] = None
    error: Optional[str] = None
    
    # Timing
    received_at: datetime = Field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    
    # Helper properties for quick access
    @property
    def task_id(self) -> str:
        return self.task.task_id
    
    @property
    def tool(self) -> str:
        return self.task.tool
    
    @property
    def depends_on(self) -> List[str]:
        return self.task.depends_on
    
    @property
    def lifecycle_messages(self) -> Optional[LifecycleMessages]:
        return self.task.lifecycle_messages
    
    @property
    def control(self) -> Optional[TaskControl]:
        return self.task.control


class ExecutionState(BaseModel):
    """
    User's execution state.
    Tracks all tasks for a user session.
    """
    user_id: str
    tasks: Dict[str, TaskRecord] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    
    def add_task(self, record: TaskRecord):
        """Add a task to state"""
        self.tasks[record.task_id] = record
        self.updated_at = datetime.now()
    
    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        """Get task by ID"""
        return self.tasks.get(task_id)
    
    def get_task_output(self, task_id: str) -> Optional[TaskOutput]:
        """Get task output by ID"""
        task = self.tasks.get(task_id)
        return task.output if task else None
    
    def update_task_status(self, task_id: str, status: TaskStatus):
        """Update task status"""
        task = self.tasks.get(task_id)
        if task:
            task.status = status
            self.updated_at = datetime.now()
    
    def get_tasks_by_status(self, status: TaskStatus) -> List[TaskRecord]:
        """Get all tasks with specific status"""
        return [task for task in self.tasks.values() if task.status == status]
    
    def get_completed_task_ids(self) -> List[str]:
        """Get IDs of all completed tasks"""
        return [
            task_id for task_id, task in self.tasks.items()
            if task.status == "completed"
        ]
