# client_core/tools/base.py
"""
Base classes for client-side tools with schema validation.
"""

from typing import Dict, Any, Optional
from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)


class ToolOutput:
    """
    Tool execution output.
    
    Matches TaskOutput structure for seamless conversion.
    """
    def __init__(self, success: bool, data: Dict[str, Any], error: Optional[str] = None):
        self.success = success
        self.data = data
        self.error = error
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error
        }


class BaseTool(ABC):
    """
    Base class for all client-side tools.
    
    Provides:
    - Automatic input validation from tool_registry.json
    - Automatic output validation
    - Error handling
    - Logging
    
    Subclasses must implement:
    - get_tool_name() -> str
    - _execute(inputs) -> ToolOutput
    """
    
    def __init__(self):
        self.tool_name = self.get_tool_name()
        self.logger = logging.getLogger(f"client.tool.{self.tool_name}")
        
        # Schema will be injected after tool registry loads
        self._params_schema: Optional[Dict[str, Any]] = None
        self._output_schema: Optional[Dict[str, Any]] = None
    
    @abstractmethod
    def get_tool_name(self) -> str:
        """Return tool name (must match tool_registry.json)."""
        pass
    
    @abstractmethod
    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """
        Execute the tool (implement this in child classes).
        
        Args:
            inputs: Validated inputs (guaranteed to match schema)
            
        Returns:
            ToolOutput with results
        """
        pass
    
    def set_schemas(self, params_schema: Dict[str, Any], output_schema: Dict[str, Any]):
        """
        Set schemas from tool_registry.json.
        Called by loader after registry loads.
        """
        self._params_schema = params_schema
        self._output_schema = output_schema
    
    async def execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """
        Execute with validation and error handling.
        
        This is the PUBLIC method called by executors.
        """
        try:
            # 1. Validate inputs against schema
            if self._params_schema:
                validation_error = self._validate_inputs(inputs)
                if validation_error:
                    return ToolOutput(
                        success=False,
                        data={},
                        error=f"Input validation failed: {validation_error}"
                    )
            
            # 2. Execute actual tool
            self.logger.info(f"Executing {self.tool_name}")
            result = await self._execute(inputs)
            
            # 3. Validate output against schema
            if self._output_schema and result.success:
                output_error = self._validate_output(result.data)
                if output_error:
                    self.logger.warning(f"Output validation failed: {output_error}")
            
            if result.success:
                self.logger.info(f"✅ {self.tool_name} succeeded")
            else:
                self.logger.warning(f"⚠️  {self.tool_name} failed: {result.error}")
            
            return result
            
        except Exception as e:
            self.logger.error(f"❌ {self.tool_name} error: {e}")
            return ToolOutput(
                success=False,
                data={},
                error=str(e)
            )
    
    def _validate_inputs(self, inputs: Dict[str, Any]) -> Optional[str]:
        """
        Validate inputs against params_schema.
        
        Returns:
            Error message if validation fails, None if success
        """
        if not self._params_schema:
            return None
        
        for param_name, param_def in self._params_schema.items():
            required = param_def.get("required", False)
            param_type = param_def.get("type")
            
            # Check required params
            if required and param_name not in inputs:
                return f"Missing required parameter: {param_name}"
            
            # Type checking (basic)
            if param_name in inputs:
                value = inputs[param_name]
                
                if param_type == "string" and not isinstance(value, str):
                    return f"Parameter '{param_name}' must be string, got {type(value).__name__}"
                
                elif param_type == "integer" and not isinstance(value, int):
                    return f"Parameter '{param_name}' must be integer, got {type(value).__name__}"
                
                elif param_type == "boolean" and not isinstance(value, bool):
                    return f"Parameter '{param_name}' must be boolean, got {type(value).__name__}"
                
                elif param_type == "array" and not isinstance(value, list):
                    return f"Parameter '{param_name}' must be array, got {type(value).__name__}"
        
        return None
    
    def _validate_output(self, data: Dict[str, Any]) -> Optional[str]:
        """
        Validate output against output_schema.
        
        Returns:
            Error message if validation fails, None if success
        """
        if not self._output_schema:
            return None
        
        expected_data = self._output_schema.get("data", {})
        
        for field_name in expected_data.keys():
            if field_name not in data:
                return f"Missing output field: {field_name}"
        
        return None
    
    def get_input(self, inputs: Dict[str, Any], param_name: str, default: Any = None) -> Any:
        """
        Get input value with default fallback.
        """
        if param_name in inputs:
            return inputs[param_name]
        
        if self._params_schema and param_name in self._params_schema:
            schema_default = self._params_schema[param_name].get("default")
            if schema_default is not None:
                return schema_default
        
        return default


class ToolInstanceRegistry:
    """
    Registry that holds tool INSTANCES (not just metadata).
    Loaded once at client startup.
    
    Provides O(1) lookup for tool execution.
    """
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self.tool_instances: Dict[str, BaseTool] = {}
            self.logger = logging.getLogger("client.ToolInstanceRegistry")
            ToolInstanceRegistry._initialized = True
    
    def register(self, tool: BaseTool):
        """Register a tool instance."""
        tool_name = tool.get_tool_name()
        self.tool_instances[tool_name] = tool
        self.logger.info(f"✅ Registered client tool: {tool_name}")
    
    def get(self, tool_name: str) -> Optional[BaseTool]:
        """Get tool instance by name (O(1) dict lookup!)."""
        return self.tool_instances.get(tool_name)
    
    def has(self, tool_name: str) -> bool:
        """Check if tool instance exists."""
        return tool_name in self.tool_instances
    
    def list_tools(self) -> list[str]:
        """List all registered tool names."""
        return list(self.tool_instances.keys())
    
    def count(self) -> int:
        """Count registered tools."""
        return len(self.tool_instances)
    
    def clear(self):
        """Clear all registered tools."""
        self.tool_instances.clear()


# Global instance registry
_client_tool_registry = ToolInstanceRegistry()


def get_client_tool_registry() -> ToolInstanceRegistry:
    """Get global client tool instance registry."""
    return _client_tool_registry


def get_client_tool(tool_name: str) -> Optional[BaseTool]:
    """
    Get tool instance by name.
    
    This is FAST! Just dict lookup!
    """
    return _client_tool_registry.get(tool_name)
