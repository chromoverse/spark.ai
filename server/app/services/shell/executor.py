"""ShellExecutor — async subprocess runner with security and approval."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from app.services.shell.sandbox import SecuritySandbox
from app.services.shell.session_manager import ShellSessionManager
from app.services.shell.user_permissions import get_user_permission_store

logger = logging.getLogger(__name__)


@dataclass
class ShellResult:
    success: bool
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    working_dir: str = ""
    error: str = ""
    needs_approval: bool = False
    approval_question: str = ""


class ShellExecutor:
    def __init__(self):
        self.sandbox = SecuritySandbox()
        self.session_manager = ShellSessionManager()

    async def execute(
        self,
        command: str,
        *,
        user_id: str,
        working_dir: Optional[str] = None,
        timeout_s: float = 30.0,
    ) -> ShellResult:
        if not command.strip():
            return ShellResult(success=False, exit_code=-1, error="Empty command")

        # 1. Security check
        allowed, reason = self.sandbox.validate(command)
        if not allowed and reason != "requires_approval":
            return ShellResult(success=False, exit_code=-1, error=reason)

        # 2. If requires_approval, check persistent permissions
        if reason == "requires_approval":
            perm_store = get_user_permission_store()
            if not perm_store.is_permitted(user_id, command):
                return ShellResult(
                    success=False, exit_code=-1,
                    error="approval_required",
                    needs_approval=True,
                    approval_question=f"Allow command: {command}?",
                )

        # 3. Resolve cwd
        cwd = self.session_manager.get_cwd(user_id, working_dir)

        # 4. Build env
        env = self.session_manager.build_env(user_id)

        # 5. Execute
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd),
                env=env,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_s
            )
            stdout = stdout_bytes.decode("utf-8", errors="replace")[:10000]
            stderr = stderr_bytes.decode("utf-8", errors="replace")[:5000]

            # Track cd commands
            first_token = command.strip().split()[0].lower()
            if first_token == "cd" and proc.returncode == 0:
                parts = command.strip().split(maxsplit=1)
                if len(parts) > 1:
                    self.session_manager.update_cwd(user_id, parts[1].strip())

            return ShellResult(
                success=(proc.returncode == 0),
                exit_code=proc.returncode or 0,
                stdout=stdout,
                stderr=stderr,
                working_dir=str(cwd),
            )
        except asyncio.TimeoutError:
            return ShellResult(success=False, exit_code=-1, error=f"Timed out after {timeout_s}s")
        except Exception as e:
            return ShellResult(success=False, exit_code=-1, error=str(e))


_instance: Optional[ShellExecutor] = None


def get_shell_executor() -> ShellExecutor:
    global _instance
    if _instance is None:
        _instance = ShellExecutor()
    return _instance
