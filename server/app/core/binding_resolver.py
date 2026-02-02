# app/core/binding_resolver.py
"""
High-Performance Input Binding Resolver

Resolves JSONPath bindings from task outputs with:
- Zero-copy data access
- Minimal overhead
- Fail-fast validation
"""

import logging
from typing import Any, Dict, Optional
from jsonpath_ng import parse
from jsonpath_ng.exceptions import JsonPathParserError

from app.core.models import TaskRecord, ExecutionState

logger = logging.getLogger(__name__)


class BindingResolver:
    """
    Fast input binding resolver
    
    Resolves input_bindings like:
    {
        "folder_path": "$.task_create_folder.data.path",
        "content": "$.task_fetch_data.data.text"
    }
    
    Into actual values from completed task outputs
    """
    
    def __init__(self):
        # Cache compiled JSONPath expressions for speed
        self._path_cache: Dict[str, Any] = {}
    
    def resolve_inputs(
        self, 
        task: TaskRecord, 
        state: ExecutionState
    ) -> Dict[str, Any]:
        """
        Resolve task inputs (static + bindings)
        
        Args:
            task: Task to resolve inputs for
            state: User execution state with completed tasks
            
        Returns:
            Resolved inputs dictionary
            
        Performance: O(n) where n = number of bindings (typically 1-3)
        """
        # Start with static inputs
        resolved = dict(task.task.inputs)
        
        # No bindings? Fast path out
        if not task.task.input_bindings:
            return resolved
        
        # Resolve each binding
        for param_name, jsonpath_expr in task.task.input_bindings.items():
            try:
                value = self._resolve_single_binding(jsonpath_expr, state)
                
                if value is not None:
                    resolved[param_name] = value
                    logger.debug(f"  ✅ Resolved {param_name} from {jsonpath_expr}")
                else:
                    logger.warning(f"  ⚠️ Binding returned None: {jsonpath_expr}")
                    
            except Exception as e:
                logger.error(f"  ❌ Failed to resolve {param_name}: {e}")
                # Don't fail entire task - let tool handle missing input
        
        return resolved
    
    def _resolve_single_binding(
        self, 
        jsonpath_expr: str, 
        state: ExecutionState
    ) -> Any:
        """
        Resolve a single JSONPath binding
        
        JSONPath format: $.task_id.data.field.subfield
        
        Example: "$.task_1.data.folder_path"
        """
        # Parse JSONPath (cached for speed)
        jsonpath = self._get_compiled_path(jsonpath_expr)
        
        # Extract task_id from path (format: $.task_id.data.field)
        parts = jsonpath_expr.split('.')
        if len(parts) < 3 or parts[0] != '$':
            raise ValueError(f"Invalid JSONPath format: {jsonpath_expr}")
        
        task_id = parts[1]
        
        # Get source task output
        source_task = state.get_task(task_id)
        
        if not source_task:
            raise ValueError(f"Source task not found: {task_id}")
        
        if source_task.status != "completed":
            raise ValueError(f"Source task not completed: {task_id} (status: {source_task.status})")
        
        if not source_task.output:
            raise ValueError(f"Source task has no output: {task_id}")
        
        # Create data structure for JSONPath to traverse
        # Format: {"task_id": {"data": {...}, "success": true}}
        data_root = {
            task_id: {
                "data": source_task.output.data,
                "success": source_task.output.success,
                "error": source_task.output.error
            }
        }
        
        # Execute JSONPath query
        matches = jsonpath.find(data_root)
        
        if not matches:
            raise ValueError(f"JSONPath matched nothing: {jsonpath_expr}")
        
        # Return first match (JSONPath can return multiple)
        return matches[0].value
    
    def _get_compiled_path(self, expr: str) -> Any:
        """Get cached or compile new JSONPath expression"""
        if expr not in self._path_cache:
            try:
                self._path_cache[expr] = parse(expr)
            except JsonPathParserError as e:
                raise ValueError(f"Invalid JSONPath syntax: {expr}") from e
        
        return self._path_cache[expr]
    
    def validate_bindings(
        self, 
        task: TaskRecord, 
        state: ExecutionState
    ) -> tuple[bool, Optional[str]]:
        """
        Check if all bindings can be resolved
        
        Returns: (can_resolve, error_message)
        
        Fast validation before execution - prevents runtime errors
        """
        if not task.task.input_bindings:
            return True, None
        
        for param_name, jsonpath_expr in task.task.input_bindings.items():
            # Extract task_id
            parts = jsonpath_expr.split('.')
            if len(parts) < 3:
                return False, f"Invalid binding format: {jsonpath_expr}"
            
            task_id = parts[1]
            
            # Check if dependency is completed
            dep_task = state.get_task(task_id)
            
            if not dep_task:
                return False, f"Dependency not found: {task_id}"
            
            if dep_task.status != "completed":
                return False, f"Dependency not completed: {task_id}"
            
            if not dep_task.output or not dep_task.output.success:
                return False, f"Dependency failed: {task_id}"
        
        return True, None


# Global singleton
_resolver: Optional[BindingResolver] = None


def get_binding_resolver() -> BindingResolver:
    """Get global binding resolver"""
    global _resolver
    if _resolver is None:
        _resolver = BindingResolver()
    return _resolver