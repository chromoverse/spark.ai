# client_core/executor/tool_executor.py
"""
Client-Side Tool Executor

Executes client-side tools using preloaded tool instances.
"""

import logging
from ..models import TaskRecord, TaskOutput
from app.agent.shared.tools.loader import get_tool_for_execution
from app.agent.shared.registry.loader import get_tool_registry

logger = logging.getLogger(__name__)


class ClientToolExecutor:
    """
    Executes client-side tools.
    
    Uses preloaded tool instances (loaded at startup).
    Just dict lookup - SUPER FAST!
    """
    
    def __init__(self):
        # Use shared registry
        self.schema_registry = get_tool_registry()
        logger.info("✅ Client Tool Executor initialized (Shared Registry)")
    
    async def execute(
        self, 
        task: TaskRecord, 
        resolved_inputs: dict
    ) -> TaskOutput:
        """
        Execute a task using preloaded tool instance.
        
        Args:
            task: TaskRecord with full task context
            resolved_inputs: Inputs after binding resolution
            
        Returns:
            TaskOutput with results
        """
        tool_name = task.tool
        
        # Validate tool exists in schema registry
        # (schema_registry.get_tool returns ToolMetadata or None)
        if not self.schema_registry.get_tool(tool_name):
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
                error=f"Tool '{tool_name}' not implemented in client"
            )
        
        try:
            # Execute tool (validation happens inside tool.execute())
            logger.info(f"Executing client tool: {tool_name}")
            output = await tool.execute(resolved_inputs)
            
            # Convert to TaskOutput format
            return TaskOutput(
                success=output.success,
                data=output.data,
                error=output.error
            )
            
        except Exception as e:
            logger.error(f"Client tool execution error ({tool_name}): {e}")
            return TaskOutput(
                success=False,
                data={},
                error=str(e)
            )


# Global singleton
_client_executor = None


def get_client_executor() -> ClientToolExecutor:
    """Get global client executor instance."""
    global _client_executor
    if _client_executor is None:
        _client_executor = ClientToolExecutor()
    return _client_executor


def init_client_executor() -> ClientToolExecutor:
    """Initialize client executor at startup."""
    global _client_executor
    _client_executor = ClientToolExecutor()
    return _client_executor
