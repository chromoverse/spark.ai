# app/tools/loader.py
"""
Tool Loader - Loads ALL tools at startup

This runs ONCE when server starts:
1. Creates all tool instances
2. Injects schemas from tool_registry.json
3. Registers in global registry

During task execution:
- Just dict lookup to get tool instance (super fast!)
"""

import logging
from app.tools.base import get_tool_instance_registry, BaseTool
from app.registry.loader import get_tool_registry

# Import all tool classes
from app.tools.web.search import WebSearchTool
from app.tools.file_system.operations import (
    CreateFileTool,
    FolderCreateTool,
    FileCopyTool,
    FileSearchTool
)

logger = logging.getLogger(__name__)


def load_all_tools():
    """
    Load and register ALL tools at startup
    
    This creates tool instances and injects schemas from tool_registry.json
    
    Called ONCE in main.py during server startup
    """
    # Auto-load check
    instance_registry = get_tool_instance_registry()
    if instance_registry.count() > 0:
        return instance_registry

    logger.info("="*70)
    logger.info("🔧 Loading Tool Instances")
    logger.info("="*70)
    
    schema_registry = get_tool_registry()
    
    # Create all tool instances
    tools = [
        # Web tools
        WebSearchTool(),
        
        # File system tools
        CreateFileTool(),
        FolderCreateTool(),
        FileCopyTool(),
        FileSearchTool(),
        
        # Add more tools here as you implement them
        # SystemInfoTool(),
        # OpenAppTool(),
        # CloseAppTool(),
        # etc.
    ]
    
    # Register each tool and inject its schema
    for tool in tools:
        tool_name = tool.get_tool_name()
        
        # Get schema from tool_registry.json
        tool_metadata = schema_registry.get_tool(tool_name)
        
        if tool_metadata:
            # Inject schemas into tool instance
            tool.set_schemas(
                params_schema=tool_metadata.params_schema,
                output_schema=tool_metadata.output_schema
            )
            logger.info(f"  🔗 Injected schemas for: {tool_name}")
        else:
            logger.warning(f"  ⚠️  No schema found for: {tool_name}")
        
        # Register in global registry
        instance_registry.register(tool)
    
    logger.info("="*70)
    logger.info(f"✅ Loaded {instance_registry.count()} tool instances")
    logger.info(f"   Tools ready: {', '.join(instance_registry.list_tools())}")
    logger.info("="*70)
    
    return instance_registry


def get_tool_for_execution(tool_name: str) -> BaseTool | None:
    """
    Get tool instance for execution
    
    This is called during task execution (FAST!)
    Just a dict lookup - no loading overhead!
    
    Used by:
    - ServerToolExecutor
    - ClientToolExecutor (in Electron app)
    """
    # Auto-load if needed
    if get_tool_instance_registry().count() == 0:
        load_all_tools()

    from app.tools.base import get_tool_instance
    return get_tool_instance(tool_name)