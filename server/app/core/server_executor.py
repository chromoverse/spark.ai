# app/core/server_executor.py
"""
Server Tool Executor

Executes server-side tools using preloaded tool instances
"""

import logging
from app.core.models import TaskRecord, TaskOutput
from app.registry.loader import get_tool_registry as get_schema_registry
from app.tools.loader import get_tool_for_execution

logger = logging.getLogger(__name__)


class ServerToolExecutor:
    """
    Executes server-side tools
    
    ✅ Uses preloaded tool instances (loaded at startup)
    ✅ Just dict lookup - SUPER FAST!
    ✅ Tools handle their own validation
    """
    
    def __init__(self):
        self.schema_registry = get_schema_registry()
        logger.info("✅ Server Tool Executor initialized")
    
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
        
        try:
            # Execute tool (validation happens inside tool.execute())
            logger.info(f"Executing tool: {tool_name}")
            output = await tool.execute(inputs)
            
            # Convert to TaskOutput format
            return TaskOutput(
                success=output.success,
                data=output.data,
                error=output.error
            )
            
        except Exception as e:
            logger.error(f"Tool execution error ({tool_name}): {e}")
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