# app/registry/loader.py
"""
Tool Registry Loader - Singleton Pattern
Loads tool_registry.json at startup and provides global access
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_TOOL_REGISTRY = {}

@dataclass
class ToolMetadata:
    """Structured tool metadata"""
    tool_name: str
    description: str
    execution_target: str  # "client" or "server"
    params_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    metadata: Dict[str, Any]
    category: str


class ToolRegistry:
    """
    Singleton class to manage tool registry
    Loads once at startup, accessible globally
    """
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self.tools: Dict[str, ToolMetadata] = {}
            self.categories: Dict[str, List[str]] = {}
            self.server_tools: List[str] = []
            self.client_tools: List[str] = []
            self._initialized = True
    
    def load(self, registry_path: str = "app/registry/tool_registry.json"):
        """
        Load tool registry from JSON file
        
        Args:
            registry_path: Path to tool_registry.json
        """
        try:
            if self.tools:
                logger.warning("Tool registry already loaded. Skipping reload.")
                return
            
            path = Path(registry_path)
            print("path", path)
            
            if not path.exists():
                raise FileNotFoundError(f"Tool registry not found at {registry_path}")
            
            with open(path, "r") as f:
                data = json.load(f)
            
            logger.info("=" * 60)
            logger.info(f"📦 Loading Tool Registry v{data.get('version', 'unknown')}")
            logger.info("=" * 60)
            
            # Parse categories and tools
            categories = data.get("categories", {})
            
            for category_name, category_data in categories.items():
                tools_in_category = []
                
                for tool_def in category_data.get("tools", []):
                    tool_name = tool_def["tool_name"]
                    
                    # Create ToolMetadata
                    tool = ToolMetadata(
                        tool_name=tool_name,
                        description=tool_def["description"],
                        execution_target=tool_def["execution_target"],
                        params_schema=tool_def["params_schema"],
                        output_schema=tool_def["output_schema"],
                        metadata=tool_def.get("metadata", {}),
                        category=category_name
                    )
                    
                    # Store tool
                    self.tools[tool_name] = tool
                    tools_in_category.append(tool_name)
                    
                    # Categorize by execution target
                    if tool.execution_target == "server":
                        self.server_tools.append(tool_name)
                    elif tool.execution_target == "client":
                        self.client_tools.append(tool_name)
                    
                    logger.info(f"  ✅ Loaded: {tool_name} ({tool.execution_target})")
                
                self.categories[category_name] = tools_in_category
            
            logger.info("=" * 60)
            logger.info(f"✅ Loaded {len(self.tools)} tools from {len(self.categories)} categories")
            logger.info(f"   📡 Server tools: {len(self.server_tools)}")
            logger.info(f"   💻 Client tools: {len(self.client_tools)}")
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f"❌ Failed to load tool registry: {e}")
            raise
    
    def get_tool(self, tool_name: str) -> Optional[ToolMetadata]:
        """Get tool metadata by name"""
        if tool_name not in self.tools:
            return None
        return self.tools.get(tool_name)
    
    def validate_tool(self, tool_name: str) -> bool:
        """Check if tool exists"""
        return tool_name in self.tools
    
    def get_tools_by_target(self, target: str) -> List[str]:
        """Get all tools for specific execution target"""
        if target == "server":
            return self.server_tools.copy()
        elif target == "client":
            return self.client_tools.copy()
        return []
    
    def get_tools_by_category(self, category: str) -> List[str]:
        """Get all tools in a category"""
        return self.categories.get(category, []).copy()
    
    def get_all_tools(self) -> Dict[str, ToolMetadata]:
        """Get all registered tools"""
        return self.tools.copy()
    
    def print_summary(self):
        """Print registry summary"""
        print("\n" + "=" * 60)
        print("TOOL REGISTRY SUMMARY")
        print("=" * 60)
        print(f"Total Tools: {len(self.tools)}")
        print(f"Categories: {len(self.categories)}")
        print("\nBy Category:")
        for cat, tools in self.categories.items():
            print(f"  {cat}: {len(tools)} tools")
        print("\nBy Target:")
        print(f"  Server: {len(self.server_tools)} tools")
        print(f"  Client: {len(self.client_tools)} tools")
        print("=" * 60 + "\n")


# Global singleton instance
tool_registry = ToolRegistry()


def get_tool_registry() -> ToolRegistry:
    """Get the global tool registry instance - schemas"""
    # Auto-load if not loaded
    if not tool_registry.tools:
        tool_registry.load()
    return tool_registry


def load_tool_registry(path: str = "app/registry/tool_registry.json"):
    """Load tool registry at startup"""
    tool_registry.load(path)