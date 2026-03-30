from __future__ import annotations

import asyncio
import inspect
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class ToolOutput:
    def __init__(self, success: bool, data: Dict[str, Any], error: Optional[str] = None):
        self.success = success
        self.data = data
        self.error = error


class BaseTool(ABC):
    def __init__(self):
        self.tool_name = self.get_tool_name()
        self.logger = logging.getLogger(f"tool.{self.tool_name}")
        self._params_schema: Optional[Dict[str, Any]] = None
        self._output_schema: Optional[Dict[str, Any]] = None

    @abstractmethod
    def get_tool_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        raise NotImplementedError

    def set_schemas(self, params_schema: Dict[str, Any], output_schema: Dict[str, Any]) -> None:
        self._params_schema = params_schema
        self._output_schema = output_schema

    async def execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            if self._params_schema:
                validation_error = self._validate_inputs(inputs)
                if validation_error:
                    return ToolOutput(
                        success=False,
                        data={},
                        error=f"Input validation failed: {validation_error}",
                    )

            if inspect.iscoroutinefunction(self._execute):
                result = await self._execute(inputs)
            else:
                result = await asyncio.to_thread(self._execute, inputs)

            if self._output_schema and result.success:
                output_error = self._validate_output(result.data)
                if output_error:
                    self.logger.warning("Output validation failed: %s", output_error)

            return result
        except Exception as exc:
            self.logger.error("%s error: %s", self.tool_name, exc)
            return ToolOutput(success=False, data={}, error=str(exc))

    def _validate_inputs(self, inputs: Dict[str, Any]) -> Optional[str]:
        if not self._params_schema:
            return None

        for param_name, param_def in self._params_schema.items():
            required = param_def.get("required", False)
            param_type = param_def.get("type")

            if required and param_name not in inputs:
                return f"Missing required parameter: {param_name}"

            if param_name in inputs:
                value = inputs[param_name]
                if param_type == "string" and not isinstance(value, str):
                    return f"Parameter '{param_name}' must be string, got {type(value).__name__}"
                if param_type == "integer" and not isinstance(value, int):
                    return f"Parameter '{param_name}' must be integer, got {type(value).__name__}"
                if param_type == "boolean" and not isinstance(value, bool):
                    return f"Parameter '{param_name}' must be boolean, got {type(value).__name__}"
                if param_type == "array" and not isinstance(value, list):
                    return f"Parameter '{param_name}' must be array, got {type(value).__name__}"

        return None

    def _validate_output(self, data: Dict[str, Any]) -> Optional[str]:
        if not self._output_schema:
            return None

        expected_data = self._output_schema.get("data", {})
        for field_name in expected_data.keys():
            if field_name not in data:
                return f"Missing output field: {field_name}"
        return None

    def get_input(self, inputs: Dict[str, Any], param_name: str, default: Any = None) -> Any:
        if param_name in inputs:
            return inputs[param_name]
        if self._params_schema and param_name in self._params_schema:
            schema_default = self._params_schema[param_name].get("default")
            if schema_default is not None:
                return schema_default
        return default


class ToolInstanceRegistry:
    _instance: "ToolInstanceRegistry | None" = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.tool_instances: Dict[str, BaseTool] = {}
            self.logger = logging.getLogger("ToolInstanceRegistry")
            self._initialized = True

    def register(self, tool: BaseTool) -> None:
        tool_name = tool.get_tool_name()
        self.tool_instances[tool_name] = tool
        self.logger.info("Registered tool instance: %s", tool_name)

    def get(self, tool_name: str) -> Optional[BaseTool]:
        return self.tool_instances.get(tool_name)

    def has(self, tool_name: str) -> bool:
        return tool_name in self.tool_instances

    def list_tools(self) -> list[str]:
        return list(self.tool_instances.keys())

    def count(self) -> int:
        return len(self.tool_instances)


_tool_instance_registry = ToolInstanceRegistry()


def get_tool_instance_registry() -> ToolInstanceRegistry:
    return _tool_instance_registry


def get_tool_instance(tool_name: str) -> Optional[BaseTool]:
    return _tool_instance_registry.get(tool_name)
