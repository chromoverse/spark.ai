# app/kernel/server_executor.py
"""
Server Tool Executor

Executes server-side tools using preloaded tool instances
"""

import logging
import time
from app.kernel.execution.execution_models import TaskRecord, TaskOutput
from app.plugins.tools.registry_loader import get_tool_registry as get_schema_registry
from app.plugins.tools.tool_instance_loader import get_tool_for_execution
from app.kernel.contracts.models import KernelEvent
from app.kernel.eventing.event_bus import emit_kernel_event

logger = logging.getLogger(__name__)


class ServerToolExecutor:
    """
    Executes server-side tools
    
    Uses preloaded tool instances (loaded at startup)
    Just dict lookup - SUPER FAST!
    Tools handle their own validation
    """
    
    def __init__(self):
        self.schema_registry = get_schema_registry()
        logger.info("Server Tool Executor initialized")
    
    async def execute(self, task: TaskRecord) -> TaskOutput:
        """
        Execute a task using preloaded tool instance
        
        Args:
            task: TaskRecord with full task context
            
        Returns:
            TaskOutput with results
        """
        tool_name = task.tool
        
        # Validate tool exists in schema registry
        if not self.schema_registry.validate_tool(tool_name):
            return TaskOutput(
                success=False,
                data={},
                error=f"Tool '{tool_name}' not found in registry"
            )
        
        # Get preloaded tool instance (FAST! Just dict lookup!)
        tool = get_tool_for_execution(tool_name)
        
        if not tool:
            return TaskOutput(
                success=False,
                data={},
                error=f"Tool '{tool_name}' not implemented yet"
            )
        
        # Get inputs (use resolved_inputs if available)
        inputs = task.resolved_inputs if task.resolved_inputs else task.task.inputs
        user_id = str(inputs.get("_user_id", "guest"))
        t0 = time.perf_counter()
        
        try:
            # Execute tool (validation happens inside tool.execute())
            logger.info(f"Executing tool: {tool_name}")
            output = await tool.execute(inputs)
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)

            event_type = "tool_invoked" if output.success else "tool_failed"
            await emit_kernel_event(
                KernelEvent(
                    event_type=event_type,
                    user_id=user_id,
                    task_id=task.task_id,
                    tool_name=tool_name,
                    status="success" if output.success else "failed",
                    payload={
                        "latency_ms": latency_ms,
                        "error": output.error,
                    },
                )
            )
            
            # Convert to TaskOutput format
            return TaskOutput(
                success=output.success,
                data=output.data,
                error=output.error
            )
            
        except Exception as e:
            logger.error(f"Tool execution error ({tool_name}): {e}")
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            await emit_kernel_event(
                KernelEvent(
                    event_type="tool_failed",
                    user_id=user_id,
                    task_id=task.task_id,
                    tool_name=tool_name,
                    status="failed",
                    payload={
                        "latency_ms": latency_ms,
                        "error": str(e),
                    },
                )
            )
            return TaskOutput(
                success=False,
                data={},
                error=str(e)
            )


# Global singleton
_server_executor = None


def get_server_executor() -> ServerToolExecutor:
    """Get global server executor instance"""
    global _server_executor
    if _server_executor is None:
        _server_executor = ServerToolExecutor()
    return _server_executor


def init_server_executor() -> ServerToolExecutor:
    """Initialize server executor at startup"""
    global _server_executor
    _server_executor = ServerToolExecutor()
    return _server_executor




