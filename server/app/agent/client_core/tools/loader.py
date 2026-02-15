# client_core/tools/loader.py
"""
Client Tool Loader

Loads ALL client tools at startup with schemas from bundled registry.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from .base import get_client_tool_registry, BaseTool

# Import all client tool classes
from .file_system.operations import (
    CreateFileTool,
    FolderCreateTool,
    FileCopyTool,
    FileSearchTool,
    FileSearchTool,
    FileReadTool
)
from .system.operations import OpenAppTool, CloseAppTool

logger = logging.getLogger(__name__)


class ClientToolSchemaRegistry:
    """
    Registry for tool schemas loaded from bundled tool_registry.json.
    """
    
    def __init__(self):
        self.tools: Dict[str, Dict[str, Any]] = {}
        self.loaded = False
    
    def load_from_file(self, path: str) -> bool:
        """Load schemas from tool_registry.json."""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Extract tools from category-based structure
            # Format: {"categories": {"system": {"tools": [...]}, ...}}
            categories = data.get("categories", {})
            for category_name, category_data in categories.items():
                for tool in category_data.get("tools", []):
                    tool_name = tool.get("tool_name")
                    if tool_name:
                        self.tools[tool_name] = tool
            
            self.loaded = True
            
            logger.info(f"✅ Loaded {len(self.tools)} tool schemas from registry")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to load tool registry: {e}")
            return False
    
    def get_tool_schema(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Get schema for a specific tool."""
        return self.tools.get(tool_name)
    
    def validate_tool(self, tool_name: str) -> bool:
        """Check if tool exists in registry."""
        return tool_name in self.tools


# Global schema registry
_schema_registry: Optional[ClientToolSchemaRegistry] = None


def get_client_schema_registry() -> ClientToolSchemaRegistry:
    """Get global client schema registry."""
    global _schema_registry
    if _schema_registry is None:
        _schema_registry = ClientToolSchemaRegistry()
    return _schema_registry


def load_client_tools() -> None:
    """
    Load and register ALL client tools at startup.
    
    This:
    1. Loads schema from bundled tool_registry.json
    2. Creates tool instances
    3. Injects schemas
    4. Registers in global registry
    """
    logger.info("="*70)
    logger.info("🔧 Loading Client Tool Instances")
    logger.info("="*70)
    
    instance_registry = get_client_tool_registry()
    schema_registry = get_client_schema_registry()
    
    # Clear any existing tools
    instance_registry.clear()
    
    # Load schemas from BUNDLED registry (inside client_core/registry/)
    current_dir = Path(__file__).parent
    registry_path = current_dir.parent / "registry" / "tool_registry.json"
    
    if registry_path.exists():
        schema_registry.load_from_file(str(registry_path))
    else:
        logger.warning(f"⚠️  Tool registry not found at: {registry_path}")
    
    # Create all tool instances
    tools: list[BaseTool] = [
        # File system tools
        CreateFileTool(),
        FolderCreateTool(),
        FileCopyTool(),
        FileSearchTool(),
        FileReadTool(),
        
        # System tools
        OpenAppTool(),
        CloseAppTool(),
        
        # Add more client tools here
    ]
    
    # Register each tool and inject its schema
    for tool in tools:
        tool_name = tool.get_tool_name()
        
        tool_schema = schema_registry.get_tool_schema(tool_name)
        
        if tool_schema:
            tool.set_schemas(
                params_schema=tool_schema.get("params_schema", {}),
                output_schema=tool_schema.get("output_schema", {})
            )
            logger.info(f"  🔗 Injected schemas for: {tool_name}")
        else:
            logger.warning(f"  ⚠️  No schema found for: {tool_name}")
        
        instance_registry.register(tool)
    
    logger.info("="*70)
    logger.info(f"✅ Loaded {instance_registry.count()} client tool instances")
    logger.info(f"   Tools ready: {', '.join(instance_registry.list_tools())}")
    logger.info("="*70)


def get_client_tool_for_execution(tool_name: str) -> Optional[BaseTool]:
    """
    Get client tool instance for execution.
    
    This is called during task execution (FAST!).
    """
    from .base import get_client_tool
    return get_client_tool(tool_name)
