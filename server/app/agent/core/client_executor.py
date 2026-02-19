# app/agent/core/client_executor.py
"""
Client Tool Executor — lives inside core/

Executes client-side tools (app_open, folder_create, etc.) using
the shared tool registry and loader. Uses core.models only.

Identical pattern to server_executor.py — just calls tool.execute()
with resolved inputs.
"""

import logging
from app.agent.core.models import TaskRecord, TaskOutput
from app.agent.shared.registry.loader import get_tool_registry as get_schema_registry
from app.agent.shared.tools.loader import get_tool_for_execution

logger = logging.getLogger(__name__)


class ClientToolExecutor:
    """
    Executes client-side tools (file ops, app control, etc.)
    
    ✅ Uses shared tool registry (same tools loaded at startup)
    ✅ Uses core.models (no client_core dependency)
    ✅ Just dict lookup — SUPER FAST
    """
    
    def __init__(self):
        self.schema_registry = get_schema_registry()
        logger.info("✅ Client Tool Executor initialized (core)")
    
    async def execute(self, task: TaskRecord, resolved_inputs: dict) -> TaskOutput:
        """
        Execute a client task using preloaded tool instance.
        
        Args:
            task: TaskRecord from core.models
            resolved_inputs: Inputs after binding resolution
            
        Returns:
            TaskOutput with results
        """
        tool_name = task.tool
        
        # Validate tool exists
        if not self.schema_registry.validate_tool(tool_name):
            return TaskOutput(
                success=False,
                data={},
                error=f"Tool '{tool_name}' not found in registry"
            )
        
        # Get preloaded tool instance (FAST dict lookup)
        tool = get_tool_for_execution(tool_name)
        
        if not tool:
            return TaskOutput(
                success=False,
                data={},
                error=f"Tool '{tool_name}' not implemented"
            )
        
        try:
            logger.info(f"Executing client tool: {tool_name}")
            output = await tool.execute(resolved_inputs)
            
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
    """Get global client executor instance"""
    global _client_executor
    if _client_executor is None:
        _client_executor = ClientToolExecutor()
    return _client_executor


def init_client_executor() -> ClientToolExecutor:
    """Initialize client executor at startup"""
    global _client_executor
    _client_executor = ClientToolExecutor()
    return _client_executor
