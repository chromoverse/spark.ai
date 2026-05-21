"""shell_execute tool."""
from __future__ import annotations
from typing import Any, Dict
from app.plugins.tools.tool_base import BaseTool, ToolOutput


class ShellExecuteTool(BaseTool):
    """Execute a single shell command on the host system."""

    TOOL_DESCRIPTION = "Execute a single shell command on the host system. Use PowerShell syntax on Windows. Set working_dir to the target directory from SYSTEM PATHS when the user references a known folder."
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA: Dict[str, Any] = {
        "command": {"type": "string", "required": True, "description": "PowerShell command to execute"},
        "working_dir": {"type": "string", "required": False, "description": "Working directory — use SYSTEM PATHS (desktop, downloads, documents, etc.) when user references a folder"},
        "timeout_s": {"type": "number", "required": False, "default": 30},
    }
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {"stdout": {"type": "string"}, "stderr": {"type": "string"}, "exit_code": {"type": "integer"}, "working_dir": {"type": "string"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [
        {"user_utterance": "list files in my Documents folder", "inputs": {"command": "Get-ChildItem", "working_dir": "~/Documents"}},
        {"user_utterance": "what's in my downloads", "inputs": {"command": "Get-ChildItem | Select-Object Name,Length,LastWriteTime", "working_dir": "~/Downloads"}},
        {"user_utterance": "check disk space", "inputs": {"command": "Get-PSDrive -PSProvider FileSystem | Select-Object Name,Used,Free"}},
    ]
    SEMANTIC_TAGS = ["shell", "command", "terminal", "execute", "run"]
    TOOL_CATEGORY = "file_management"

    def get_tool_name(self) -> str:
        return "shell_execute"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        command = self.get_input(inputs, "command", "")
        working_dir = self.get_input(inputs, "working_dir", None)
        timeout_s = float(self.get_input(inputs, "timeout_s", 30) or 30)
        user_id = str(inputs.get("_user_id") or "guest").strip() or "guest"
        if not command:
            return ToolOutput(success=False, data={}, error="command is required")
        from app.services.shell.executor import get_shell_executor
        result = await get_shell_executor().execute(command, user_id=user_id, working_dir=working_dir, timeout_s=timeout_s)
        if result.needs_approval:
            return ToolOutput(success=False, data={"needs_approval": True, "command": command}, error="approval_required")
        return ToolOutput(
            success=result.success,
            data={"stdout": result.stdout, "stderr": result.stderr, "exit_code": result.exit_code, "working_dir": result.working_dir, "command": command},
            error=result.error if not result.success else None,
        )


__all__ = ["ShellExecuteTool"]
