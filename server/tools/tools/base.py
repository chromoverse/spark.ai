from __future__ import annotations

import asyncio
import inspect
import json
import logging
import subprocess as _subprocess_mod
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple, Union


# ── Input type coercion ──────────────────────────────────────────────────
# LLMs frequently emit JSON args with the wrong primitive type (e.g. an
# integer wrapped in quotes). Rather than failing the whole task we try a
# safe, lossless coercion before reporting a validation error.

_TRUE_STRINGS = {"true", "yes", "y", "on", "1"}
_FALSE_STRINGS = {"false", "no", "n", "off", "0"}


def _is_type_match(value: Any, param_type: Optional[str]) -> bool:
    """Return True when value already satisfies the expected schema type."""
    if param_type is None:
        return True
    if param_type == "string":
        return isinstance(value, str)
    if param_type == "integer":
        # bool is a subclass of int — treat it as a separate type.
        return isinstance(value, int) and not isinstance(value, bool)
    if param_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if param_type == "boolean":
        return isinstance(value, bool)
    if param_type == "array":
        return isinstance(value, list)
    if param_type == "object":
        return isinstance(value, dict)
    return True


def _coerce_value(value: Any, param_type: Optional[str]) -> Tuple[Any, bool]:
    """Best-effort safe coercion. Returns (coerced_value, success)."""
    if param_type is None or _is_type_match(value, param_type):
        return value, True

    try:
        if param_type == "integer":
            if isinstance(value, bool):
                return int(value), True
            if isinstance(value, float):
                if value.is_integer():
                    return int(value), True
                return value, False
            if isinstance(value, str):
                stripped = value.strip()
                if not stripped:
                    return value, False
                # Accept "15", "15.0", "+15", "-3"
                try:
                    return int(stripped), True
                except ValueError:
                    pass
                try:
                    f = float(stripped)
                    if f.is_integer():
                        return int(f), True
                except ValueError:
                    pass
                return value, False

        if param_type == "number":
            if isinstance(value, bool):
                return float(value), True
            if isinstance(value, str):
                stripped = value.strip()
                if not stripped:
                    return value, False
                try:
                    return float(stripped), True
                except ValueError:
                    return value, False

        if param_type == "boolean":
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if value in (0, 1):
                    return bool(value), True
                return value, False
            if isinstance(value, str):
                norm = value.strip().lower()
                if norm in _TRUE_STRINGS:
                    return True, True
                if norm in _FALSE_STRINGS:
                    return False, True
                return value, False

        if param_type == "string":
            if isinstance(value, (int, float, bool)):
                return str(value), True

        if param_type == "array":
            if isinstance(value, tuple):
                return list(value), True
            if isinstance(value, str):
                stripped = value.strip()
                if stripped.startswith("[") and stripped.endswith("]"):
                    try:
                        parsed = json.loads(stripped)
                        if isinstance(parsed, list):
                            return parsed, True
                    except json.JSONDecodeError:
                        pass
                # Fallback: comma-separated list
                if "," in stripped:
                    return [p.strip() for p in stripped.split(",") if p.strip()], True

        if param_type == "object":
            if isinstance(value, str):
                stripped = value.strip()
                if stripped.startswith("{") and stripped.endswith("}"):
                    try:
                        parsed = json.loads(stripped)
                        if isinstance(parsed, dict):
                            return parsed, True
                    except json.JSONDecodeError:
                        pass
    except Exception:
        return value, False

    return value, False


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

    # ── Non-blocking helpers for async _execute methods ──────────────────

    async def _run_subprocess(
        self,
        cmd: Union[List[str], str],
        *,
        capture_output: bool = True,
        text: bool = True,
        timeout: int = 30,
        cwd: Optional[str] = None,
        shell: bool = False,
        check: bool = False,
        **kwargs: Any,
    ) -> _subprocess_mod.CompletedProcess:
        """Non-blocking ``subprocess.run`` — safe to call from async ``_execute``.

        Offloads the blocking call to a thread so the event loop stays free.
        Accepts the same arguments as ``subprocess.run``.
        """
        return await asyncio.to_thread(
            _subprocess_mod.run,
            cmd,
            capture_output=capture_output,
            text=text,
            timeout=timeout,
            cwd=cwd,
            shell=shell,
            check=check,
            **kwargs,
        )

    @staticmethod
    async def _async_sleep(seconds: float) -> None:
        """Non-blocking sleep — use instead of ``time.sleep`` inside async ``_execute``."""
        await asyncio.sleep(seconds)

    # ── Core execution entry-point ───────────────────────────────────────

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
                self._validate_output_contract(result)

            return result
        except Exception as exc:
            self.logger.error("%s error: %s", self.tool_name, exc)
            return ToolOutput(success=False, data={}, error=str(exc))

    def _validate_output_contract(self, output: ToolOutput) -> None:
        """Warn if declared output_schema fields are missing from output.data."""
        if not output.success or not self._output_schema:
            return
        declared = set(self._output_schema.get("data", {}).keys())
        actual = set(output.data.keys()) if output.data else set()
        missing = declared - actual
        if missing:
            self.logger.warning(
                "Tool '%s' output missing declared fields: %s (has: %s)",
                self.tool_name, missing, actual,
            )

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
                if not _is_type_match(value, param_type):
                    coerced, ok = _coerce_value(value, param_type)
                    if ok:
                        self.logger.debug(
                            "Coerced '%s' from %s to %s for tool %s",
                            param_name, type(value).__name__, param_type, self.tool_name,
                        )
                        inputs[param_name] = coerced
                        continue
                    return (
                        f"Parameter '{param_name}' must be {param_type}, "
                        f"got {type(value).__name__}"
                    )

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
