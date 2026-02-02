# app/tools/schema_generator.py
"""
Auto-generate Pydantic models from tool_registry.json schemas

This runs at startup and creates type-safe input/output models for each tool
"""

from typing import Dict, Any, Optional, Type
from pydantic import BaseModel, Field, create_model
import logging

logger = logging.getLogger(__name__)


def json_type_to_python(json_type: str) -> Type:
    """
    Convert JSON schema type to Python type
    
    Maps:
    - string → str
    - integer → int
    - boolean → bool
    - number → float
    - array → list
    - object → dict
    """
    type_map = {
        "string": str,
        "integer": int,
        "boolean": bool,
        "number": float,
        "array": list,
        "object": dict
    }
    return type_map.get(json_type, Any)


def generate_input_model(tool_name: str, params_schema: Dict[str, Any]) -> Type[BaseModel]:
    """
    Generate Pydantic input model from params_schema
    
    Example:
    params_schema = {
        "query": {
            "type": "string",
            "required": true
        },
        "max_results": {
            "type": "integer",
            "required": false,
            "default": 10
        }
    }
    
    Generates:
    class WebSearchInput(BaseModel):
        query: str
        max_results: int = 10
    """
    fields = {}
    
    for param_name, param_def in params_schema.items():
        # Get type
        json_type = param_def.get("type", "string")
        python_type = json_type_to_python(json_type)
        
        # Get required and default
        required = param_def.get("required", False)
        default_value = param_def.get("default")
        
        # Build field
        if required and default_value is None:
            # Required field, no default
            fields[param_name] = (python_type, ...)
        elif default_value is not None:
            # Has default value
            fields[param_name] = (python_type, default_value)
        else:
            # Optional field, no default
            fields[param_name] = (Optional[python_type], None)
    
    # Create dynamic Pydantic model
    model_name = f"{snake_to_pascal(tool_name)}Input"
    return create_model(model_name, **fields)


def generate_output_model(tool_name: str, output_schema: Dict[str, Any]) -> Type[BaseModel]:
    """
    Generate Pydantic output model from output_schema
    
    Example:
    output_schema = {
        "success": {"type": "boolean"},
        "data": {
            "results": {"type": "array"},
            "total_results": {"type": "integer"}
        }
    }
    
    Generates:
    class WebSearchOutput(BaseModel):
        results: list
        total_results: int
    """
    # Get data fields (we skip "success" as that's in ToolOutput wrapper)
    data_schema = output_schema.get("data", {})
    
    fields = {}
    for field_name, field_def in data_schema.items():
        json_type = field_def.get("type", "string")
        python_type = json_type_to_python(json_type)
        
        # All output fields are required
        fields[field_name] = (python_type, ...)
    
    # Create dynamic Pydantic model
    model_name = f"{snake_to_pascal(tool_name)}Output"
    return create_model(model_name, **fields)


def snake_to_pascal(snake_str: str) -> str:
    """Convert snake_case to PascalCase"""
    return "".join(word.capitalize() for word in snake_str.split("_"))


def generate_models_for_tool(
    tool_name: str,
    params_schema: Dict[str, Any],
    output_schema: Dict[str, Any]
) -> tuple[Type[BaseModel], Type[BaseModel]]:
    """
    Generate both input and output models for a tool
    
    Returns:
        (InputModel, OutputModel)
    """
    input_model = generate_input_model(tool_name, params_schema)
    output_model = generate_output_model(tool_name, output_schema)
    
    logger.info(f"  📝 Generated models for {tool_name}")
    
    return input_model, output_model


# ========================================
# MODEL REGISTRY
# ========================================

class ModelRegistry:
    """
    Registry that holds generated Pydantic models
    Loaded once at startup
    """
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self.input_models: Dict[str, Type[BaseModel]] = {}
            self.output_models: Dict[str, Type[BaseModel]] = {}
            self._initialized = True
    
    def register(
        self,
        tool_name: str,
        input_model: Type[BaseModel],
        output_model: Type[BaseModel]
    ):
        """Register models for a tool"""
        self.input_models[tool_name] = input_model
        self.output_models[tool_name] = output_model
    
    def get_input_model(self, tool_name: str) -> Optional[Type[BaseModel]]:
        """Get input model for a tool"""
        return self.input_models.get(tool_name)
    
    def get_output_model(self, tool_name: str) -> Optional[Type[BaseModel]]:
        """Get output model for a tool"""
        return self.output_models.get(tool_name)


# Global model registry
_model_registry = ModelRegistry()


def get_model_registry() -> ModelRegistry:
    """Get global model registry"""
    return _model_registry


def generate_all_models_from_registry():
    """
    Generate Pydantic models for ALL tools in tool_registry.json
    
    Call this at startup after loading tool registry
    """
    from app.registry.loader import get_tool_registry
    
    logger.info("="*70)
    logger.info("📝 Generating Pydantic Models from Schemas")
    logger.info("="*70)
    
    tool_registry = get_tool_registry()
    model_registry = get_model_registry()
    
    for tool_name, tool_metadata in tool_registry.get_all_tools().items():
        try:
            input_model, output_model = generate_models_for_tool(
                tool_name,
                tool_metadata.params_schema,
                tool_metadata.output_schema
            )
            
            model_registry.register(tool_name, input_model, output_model)
            
        except Exception as e:
            logger.error(f"  ❌ Failed to generate models for {tool_name}: {e}")
    
    logger.info("="*70)
    logger.info(f"✅ Generated models for {len(model_registry.input_models)} tools")
    logger.info("="*70)
    
    return model_registry