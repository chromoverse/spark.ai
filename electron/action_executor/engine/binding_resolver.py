# client_core/engine/binding_resolver.py
"""
Client-Side Binding Resolver

Resolves input bindings using JSONPath-like expressions.
"""

import logging
import re
from typing import Any, Dict, Optional

from ..models import TaskRecord, ExecutionState

logger = logging.getLogger(__name__)


class ClientBindingResolver:
    """
    Resolves input bindings on client side.
    
    Binding format: $.task_id.data.field
    
    Examples:
        $.create_file.data.path -> output.data.path from create_file task
    """
    
    def resolve_inputs(
        self, 
        task: TaskRecord, 
        state: ExecutionState
    ) -> Dict[str, Any]:
        """
        Resolve all input bindings for a task.
        
        Merges:
        1. Static inputs from task.task.inputs
        2. Pre-resolved inputs from task.resolved_inputs
        3. Dynamic bindings from task.task.input_bindings
        
        Returns:
            Complete resolved inputs dict
        """
        # Start with static inputs
        resolved = dict(task.task.inputs)
        
        # Merge pre-resolved inputs (from server)
        resolved.update(task.resolved_inputs)
        
        # Resolve any remaining bindings
        bindings = task.task.input_bindings
        
        for param_name, binding_expr in bindings.items():
            if param_name in resolved:
                # Already resolved, skip
                continue
            
            value = self._resolve_binding(binding_expr, state)
            if value is not None:
                resolved[param_name] = value
                logger.info(f"  🔗 Resolved binding: {param_name} = {binding_expr}")
            else:
                logger.warning(f"  ⚠️  Could not resolve: {param_name} = {binding_expr}")
        
        return resolved
    
    def _resolve_binding(
        self, 
        expr: str, 
        state: ExecutionState
    ) -> Optional[Any]:
        """
        Resolve a single binding expression.
        
        Format: $.task_id.data.field_name
        
        Args:
            expr: Binding expression (e.g., "$.create_file.data.path")
            state: Execution state with completed tasks
            
        Returns:
            Resolved value or None if not found
        """
        if not expr.startswith("$."):
            logger.warning(f"Invalid binding format: {expr}")
            return None
        
        # Parse expression: $.task_id.path.to.field
        parts = expr[2:].split(".")
        
        if len(parts) < 2:
            logger.warning(f"Binding too short: {expr}")
            return None
        
        task_id = parts[0]
        path = parts[1:]
        
        # Get task output
        task_output = state.get_task_output(task_id)
        
        if not task_output:
            logger.warning(f"Task output not found: {task_id}")
            return None
        
        # Navigate path
        current = task_output.model_dump() if hasattr(task_output, 'model_dump') else task_output
        
        for key in path:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                logger.warning(f"Path not found: {key} in {expr}")
                return None
        
        return current
