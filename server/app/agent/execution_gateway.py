from __future__ import annotations

"""
Agent-facing execution gateway.

App-facing modules (socket/services/api) should import execution entrypoints
from here instead of importing kernel internals directly.
"""

from app.kernel.execution.execution_runtime import (
    LifecycleMessages,
    Task,
    TaskOutput,
    TaskRecord,
    get_client_executor,
    get_execution_engine,
    get_orchestrator,
    get_server_executor,
    get_task_emitter,
    init_client_executor,
    init_execution_engine,
    init_orchestrator,
    init_server_executor,
    init_task_emitter,
)

__all__ = [
    "LifecycleMessages",
    "Task",
    "TaskOutput",
    "TaskRecord",
    "get_client_executor",
    "get_execution_engine",
    "get_orchestrator",
    "get_server_executor",
    "get_task_emitter",
    "init_client_executor",
    "init_execution_engine",
    "init_orchestrator",
    "init_server_executor",
    "init_task_emitter",
]


