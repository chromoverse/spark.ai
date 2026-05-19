"""shell_execute tool — runs a single shell command via ShellExecutor."""
from __future__ import annotations

from typing import Any, Dict

from ..base import BaseTool, ToolOutput


class ShellExecuteTool(BaseTool):
    """Execute a shell command on the host system.

    Inputs:
    - command (string, required)
    - working_dir (string, optional)
    - timeout_s (number, optional, default 30)

    Outputs:
    - stdout (string)
    - stderr (string)
    - exit_code (integer)
    - working_dir (string)
    """

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
        result = await get_shell_executor().execute(
            command, user_id=user_id, working_dir=working_dir, timeout_s=timeout_s,
        )

        if result.needs_approval:
            return ToolOutput(
                success=False,
                data={"needs_approval": True, "command": command},
                error="approval_required",
            )

        return ToolOutput(
            success=result.success,
            data={
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.exit_code,
                "working_dir": result.working_dir,
                "command": command,
            },
            error=result.error if not result.success else None,
        )


__all__ = ["ShellExecuteTool"]
