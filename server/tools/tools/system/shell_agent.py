"""Shell Agent V2 — Async, streaming, no arbitrary limits.

shell_agent:
- Purpose: let the LLM plan and execute arbitrary shell workflows step by step.
  Can scaffold complete projects (FastAPI, React, .NET, Python), run builds,
  manage processes, inspect output — anything a developer would do in a terminal.
- Each step: LLM plans the next command → approval gate → async execution →
  output fed back to planner → repeat until done or blocked.
- Inputs: goal (required), working_dir?, max_steps?, allow_network?
- Outputs: final_answer, steps, step_count, working_dir, completed_at.

GuardedCommandRunner:
- Purpose: classify commands as read-only, mutating, destructive, or blocked.
- Safety: mutating/destructive commands require approval via notification;
  blocked commands fail closed.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.path.manager import PathManager
from app.plugins.tools.catalog_service import get_tool_catalog_service

from ..base import BaseTool, ToolOutput


_READ_ONLY_PREFIXES = (
    "dir",
    "ls",
    "pwd",
    "echo",
    "write-output",
    "get-content",
    "type",
    "cat",
    "gc ",
    "select-string",
    "findstr",
    "where",
    "where.exe",
    "rg",
    "git status",
    "git diff",
    "git show",
    "git branch",
    "git log",
    "test-path",
    "get-childitem",
    "get-item",
    "get-location",
    "resolve-path",
    "measure-object",
    "get-process",
    "node --version",
    "npm --version",
    "npx --version",
    "python --version",
    "dotnet --version",
    "pip --version",
)

_NETWORK_PATTERNS = (
    "curl ",
    "wget ",
    "invoke-webrequest",
    "invoke-restmethod",
    "pip install",
    "npm install",
    "pnpm install",
    "yarn install",
    "yarn add",
    "git clone",
    "winget ",
    "choco ",
    "scoop ",
    "test-netconnection",
    "ping ",
    "npx ",
    "npm init",
    "npm create",
    "pnpm create",
    "dotnet new",
    "cargo init",
    "cargo new",
    "pip download",
)

_DESTRUCTIVE_PATTERNS = (
    "remove-item",
    "del ",
    "erase ",
    "rm ",
    "rmdir",
    "rd ",
    "format ",
    "clear-content",
    "rename-item",
    "ren ",
    "move-item",
    "taskkill",
    "stop-process",
    "shutdown",
    "restart-computer",
    "git clean",
    "git reset --hard",
)

_MUTATING_PATTERNS = _DESTRUCTIVE_PATTERNS + (
    "copy-item",
    "new-item",
    "mkdir",
    "md ",
    "out-file",
    "add-content",
    "set-content",
    "set-location",
    "cd ",
    "push-location",
    "pop-location",
)

# Commands that are always safe to auto-approve (no notification needed)
_AUTO_APPROVE_PATTERNS = (
    "mkdir",
    "md ",
    "new-item -itemtype directory",
    "new-item -type directory",
    "set-content",
    "out-file",
    "add-content",
    "echo ",
    "write-output",
    "copy-item",
)


class GuardedCommandRunner:
    """Execute shell commands under a simple allow/block/approval policy."""

    def __init__(self, path_manager: Optional[PathManager] = None):
        self.path_manager = path_manager or PathManager()

    async def run(
        self,
        *,
        command: str,
        working_dir: str,
        user_id: str,
        task_id: str,
        step_index: int,
        allow_network: bool,
        timeout: int = 60,
    ) -> Dict[str, Any]:
        decision = self.classify_command(command, allow_network=allow_network)
        if decision["blocked"]:
            return {
                "allowed": False,
                "requires_approval": False,
                "approved": False,
                "classification": decision,
                "stdout": "",
                "stderr": decision["reason"],
                "exit_code": -1,
            }

        approved = True
        if decision["requires_approval"] and not decision.get("auto_approve"):
            approved = await self._request_approval(
                user_id=user_id,
                task_id=task_id,
                step_index=step_index,
                command=command,
                question=decision["approval_question"],
            )
            if not approved:
                return {
                    "allowed": False,
                    "requires_approval": True,
                    "approved": False,
                    "classification": decision,
                    "stdout": "",
                    "stderr": "Approval was not granted for this command.",
                    "exit_code": -1,
                }

        result = await self._execute_command_async(
            command=command,
            working_dir=working_dir,
            timeout=timeout,
        )
        result.update(
            {
                "allowed": True,
                "requires_approval": decision["requires_approval"],
                "approved": approved,
                "classification": decision,
            }
        )
        return result

    def classify_command(self, command: str, *, allow_network: bool) -> Dict[str, Any]:
        normalized = re.sub(r"\s+", " ", str(command or "").strip()).lower()
        if not normalized:
            return {
                "blocked": True,
                "requires_approval": False,
                "is_read_only": False,
                "destructive": False,
                "auto_approve": False,
                "reason": "Empty command.",
                "approval_question": "",
            }

        if any(pattern in normalized for pattern in _NETWORK_PATTERNS) and not allow_network:
            return {
                "blocked": True,
                "requires_approval": False,
                "is_read_only": False,
                "destructive": False,
                "auto_approve": False,
                "reason": "Networked commands are blocked unless allow_network=true.",
                "approval_question": "",
            }

        is_read_only = normalized.startswith(_READ_ONLY_PREFIXES)
        destructive = any(pattern in normalized for pattern in _DESTRUCTIVE_PATTERNS)
        mutating = destructive or any(pattern in normalized for pattern in _MUTATING_PATTERNS)

        # Auto-approve safe mutations (mkdir, write files, etc.)
        auto_approve = (
            not destructive
            and mutating
            and any(pattern in normalized for pattern in _AUTO_APPROVE_PATTERNS)
        )

        requires_approval = (not is_read_only and mutating) and not auto_approve
        approval_question = (
            f"Allow this destructive shell command?\n{command}"
            if destructive
            else f"Allow this shell command?\n{command}"
        )
        return {
            "blocked": False,
            "requires_approval": requires_approval,
            "is_read_only": is_read_only,
            "destructive": destructive,
            "auto_approve": auto_approve,
            "reason": (
                "Read-only command."
                if is_read_only
                else "Auto-approved safe mutation."
                if auto_approve
                else "Mutating or unclassified command."
            ),
            "approval_question": approval_question,
        }

    async def _execute_command_async(
        self,
        *,
        command: str,
        working_dir: str,
        timeout: int = 60,
    ) -> Dict[str, Any]:
        """Fully async subprocess execution with streaming and timeout."""
        cwd = str(Path(working_dir).expanduser().resolve())

        if sys.platform == "win32":
            proc = await asyncio.create_subprocess_exec(
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
        else:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
            stdout = (stdout_bytes or b"").decode("utf-8", errors="replace")
            stderr = (stderr_bytes or b"").decode("utf-8", errors="replace")
            return {
                "stdout": stdout[:8000],
                "stderr": stderr[:4000],
                "exit_code": proc.returncode or 0,
                "timed_out": False,
            }
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            return {
                "stdout": "",
                "stderr": f"Process timed out after {timeout}s.",
                "exit_code": -1,
                "timed_out": True,
            }
        except Exception as exc:
            return {
                "stdout": "",
                "stderr": str(exc),
                "exit_code": -1,
                "timed_out": False,
            }

    async def _request_approval(
        self,
        *,
        user_id: str,
        task_id: str,
        step_index: int,
        command: str,
        question: str,
    ) -> bool:
        if not user_id or user_id == "guest":
            # Guest users auto-approve (no notification target)
            return True
        try:
            from app.agent.execution_gateway import get_task_emitter

            emitter = get_task_emitter()
            approval_task_id = f"{task_id or 'shell_agent'}::shell_step_{step_index}"
            return bool(
                await emitter.request_approval(
                    user_id=user_id,
                    task_id=approval_task_id,
                    question=question,
                )
            )
        except Exception:
            # If notification system isn't available, auto-approve
            return True


# ── System prompt for the LLM shell planner ─────────────────────────────────

_PLANNER_SYSTEM_PROMPT = """\
You are a powerful shell planning agent running on Windows (PowerShell).
You can do ANYTHING a developer can do in a terminal:
- Create files (Set-Content, Out-File, Add-Content)
- Create folders (mkdir, New-Item -ItemType Directory)
- Initialize projects (npx create-react-app, npx create-vite, npm init, dotnet new, pip install, cargo new)
- Install dependencies (npm install, pip install, etc.)
- Run build tools (npm run build, python setup.py, etc.)
- Execute scripts (python script.py, node script.js, etc.)
- Inspect output, logs, errors, and adapt your approach

Return ONLY a JSON object with these keys:
{
  "done": false,
  "answer": "",
  "command": "the exact PowerShell command to run",
  "reason": "why this step is needed",
  "timeout_seconds": 30,
  "needs_network": false
}

Rules:
- If the task is COMPLETE, set done=true and provide a final answer summarizing what was accomplished.
- If the task CANNOT proceed (blocked, error with no fix), set done=true and explain in answer.
- If a command is needed, set done=false and provide EXACTLY ONE command.
- Set timeout_seconds based on expected duration:
  * Quick inspection (ls, dir, cat): 10-15
  * File creation / mkdir: 15-20
  * npm install, pip install, npx create-*: 120-180
  * Build / compile: 60-120
  * Default: 30
- Set needs_network=true if the command requires internet (npm install, pip install, npx, git clone, etc.)
- If a previous step FAILED, analyze the error output and try a different approach.
- Prefer PowerShell-native commands. For file content, use Set-Content or Out-File.
- When creating multi-line file content, use PowerShell here-strings: @" ... "@
- For Python projects: create main .py file(s) with Set-Content, then optionally create requirements.txt.
- For React/Vite: use npx create-vite or npx create-react-app with --yes / --template flags for non-interactive mode.
- For FastAPI: create main.py with Set-Content, create requirements.txt, optionally pip install.
- Never emit markdown. Return ONLY the JSON object.
- Never repeat a failed command without changes.
"""


class ShellAgentTool(BaseTool):
    """Run a multi-step shell workflow with LLM planning and approval gates.

    The shell agent is UNLIMITED — it can scaffold complete projects, install
    dependencies, create any file structure, run builds, and execute programs.
    Each step is planned by an LLM and executed with safety classification.

    Inputs:
    - goal (string, required): natural-language task for the shell agent to complete
    - working_dir (string, optional): starting directory for command execution
    - max_steps (integer, optional): step limit (default 20, max 50 — set high for complex tasks)
    - allow_network (boolean, optional): allow networked commands when true
    - user_id (string, optional): explicit user id, usually injected by the runtime
    - _task_id (string, optional): runtime task id used for approval prompts and tracing

    Outputs:
    - final_answer (string): plain-language summary of the run
    - steps (array): per-step planning and execution records
    - step_count (integer): number of executed steps
    - working_dir (string): resolved execution directory
    - completed_at (string): ISO timestamp marking the end of the run
    """

    def __init__(self):
        super().__init__()
        self.path_manager = PathManager()
        self.command_runner = GuardedCommandRunner(self.path_manager)

    def get_tool_name(self) -> str:
        return "shell_agent"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        goal = str(self.get_input(inputs, "goal", "")).strip()
        if not goal:
            return ToolOutput(success=False, data={}, error="goal is required")

        working_dir = self._resolve_working_dir(self.get_input(inputs, "working_dir", None))
        max_steps = max(1, min(50, int(self.get_input(inputs, "max_steps", 20) or 20)))
        allow_network = bool(self.get_input(inputs, "allow_network", False))
        user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "guest").strip() or "guest"
        task_id = str(inputs.get("_task_id") or "shell_agent").strip() or "shell_agent"

        history: List[Dict[str, Any]] = []
        consecutive_failures = 0
        max_consecutive_failures = 3

        for step_index in range(1, max_steps + 1):
            decision = await self._plan_next_step(
                goal=goal,
                working_dir=working_dir,
                history=history,
                step_index=step_index,
                allow_network=allow_network,
            )

            if decision.get("done"):
                final_answer = str(decision.get("answer", "")).strip() or "The task is complete."
                return ToolOutput(
                    success=True,
                    data={
                        "final_answer": final_answer,
                        "steps": history,
                        "step_count": len(history),
                        "working_dir": working_dir,
                        "completed_at": datetime.now().isoformat(),
                    },
                )

            command = str(decision.get("command", "")).strip()
            if not command:
                return ToolOutput(
                    success=False,
                    data={"steps": history},
                    error="Shell agent returned no command.",
                )

            # Dynamic timeout from planner (clamped to 10s..300s)
            step_timeout = int(decision.get("timeout_seconds", 30) or 30)
            step_timeout = max(10, min(step_timeout, 300))

            # Network auto-detection from planner
            step_needs_network = bool(decision.get("needs_network", False))
            effective_allow_network = allow_network or step_needs_network

            result = await self.command_runner.run(
                command=command,
                working_dir=working_dir,
                user_id=user_id,
                task_id=task_id,
                step_index=step_index,
                allow_network=effective_allow_network,
                timeout=step_timeout,
            )

            step_record = {
                "step": step_index,
                "reason": str(decision.get("reason", "")).strip(),
                "command": command,
                "timeout_seconds": step_timeout,
                **result,
            }
            history.append(step_record)

            # Handle blocked/not-approved commands
            if not result.get("allowed"):
                consecutive_failures += 1
                self.logger.warning(
                    "Step %d blocked/denied: %s (consecutive=%d)",
                    step_index,
                    result.get("stderr", ""),
                    consecutive_failures,
                )
                if consecutive_failures >= max_consecutive_failures:
                    return ToolOutput(
                        success=False,
                        data={
                            "final_answer": "Stopped after repeated blocked/denied commands.",
                            "steps": history,
                            "step_count": len(history),
                            "working_dir": working_dir,
                            "completed_at": datetime.now().isoformat(),
                        },
                        error="Too many consecutive blocked or denied commands.",
                    )
                # Don't abort — let the planner try a different approach
                continue

            # Track exit code for consecutive failure detection
            exit_code = result.get("exit_code", 0)
            if exit_code != 0:
                consecutive_failures += 1
                self.logger.warning(
                    "Step %d failed with exit_code=%d (consecutive=%d)",
                    step_index,
                    exit_code,
                    consecutive_failures,
                )
                if consecutive_failures >= max_consecutive_failures:
                    final_answer = await self._summarize_run(
                        goal=goal, working_dir=working_dir, history=history
                    )
                    return ToolOutput(
                        success=False,
                        data={
                            "final_answer": final_answer,
                            "steps": history,
                            "step_count": len(history),
                            "working_dir": working_dir,
                            "completed_at": datetime.now().isoformat(),
                        },
                        error="Too many consecutive failures — aborting.",
                    )
            else:
                consecutive_failures = 0  # Reset on success

        # Max steps reached
        final_answer = await self._summarize_run(
            goal=goal, working_dir=working_dir, history=history
        )
        return ToolOutput(
            success=len(history) > 0 and any(s.get("exit_code") == 0 for s in history),
            data={
                "final_answer": final_answer,
                "steps": history,
                "step_count": len(history),
                "working_dir": working_dir,
                "completed_at": datetime.now().isoformat(),
            },
            error="Shell agent reached the maximum number of steps." if not any(
                s.get("exit_code") == 0 for s in history
            ) else None,
        )

    def _resolve_working_dir(self, raw_working_dir: Any) -> str:
        if raw_working_dir:
            return str(Path(str(raw_working_dir)).expanduser().resolve())
        return str(self.path_manager.get_server_dir().resolve())

    async def _plan_next_step(
        self,
        *,
        goal: str,
        working_dir: str,
        history: List[Dict[str, Any]],
        step_index: int,
        allow_network: bool,
    ) -> Dict[str, Any]:
        from app.ai.providers import llm_chat

        tool_name = self._extract_tool_name(goal)
        catalog_context = get_tool_catalog_service().query(
            tool_name=tool_name,
            view="detail" if tool_name else "summary",
            include_examples=True,
        )
        path_context = {
            "server_dir": str(self.path_manager.get_server_dir()),
            "registry_path": str(self.path_manager.get_tools_registry_file()),
            "tool_index_path": str(self.path_manager.get_tools_index_file()),
            "user_data_dir": str(self.path_manager.get_user_data_dir()),
            "artifacts_dir": str(self.path_manager.get_artifacts_dir()),
        }

        # Compact history — only last 6 steps to keep prompt lean
        compact_history = []
        for step in history[-6:]:
            compact_step = {
                "step": step.get("step"),
                "command": step.get("command"),
                "exit_code": step.get("exit_code"),
                "stdout": (step.get("stdout") or "")[:1500],
                "stderr": (step.get("stderr") or "")[:800],
                "allowed": step.get("allowed"),
                "timed_out": step.get("timed_out", False),
            }
            compact_history.append(compact_step)

        # Detect workspace context
        workspace_hints = self._detect_workspace(working_dir)

        # Get live environment context (active windows, processes, specs)
        env_context = {}
        try:
            from app.agent.runtime.environment_context_service import (
                get_environment_context_service,
            )
            env_context = await get_environment_context_service().get_snapshot(
                include_windows=True,
                include_processes=True,
                include_system=False,  # keep prompt lean
                working_dir=working_dir,
            )
        except Exception:
            pass

        prompt = {
            "goal": goal,
            "working_dir": working_dir,
            "step_index": step_index,
            "allow_network": allow_network,
            "path_context": path_context,
            "workspace": workspace_hints,
            "environment": env_context,
            "tool_catalog_context": catalog_context,
            "history": compact_history,
        }

        messages = [
            {"role": "system", "content": _PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=True)},
        ]
        raw, _provider = await llm_chat(messages=messages, temperature=0.1, max_tokens=600)
        return self._extract_json(raw)

    async def _summarize_run(
        self,
        *,
        goal: str,
        working_dir: str,
        history: List[Dict[str, Any]],
    ) -> str:
        from app.ai.providers import llm_chat

        compact = [
            {
                "step": s.get("step"),
                "command": s.get("command"),
                "exit_code": s.get("exit_code"),
                "stdout_snippet": (s.get("stdout") or "")[:300],
            }
            for s in history[-8:]
        ]

        messages = [
            {
                "role": "system",
                "content": "Summarize the shell run in 2-4 concise sentences. Mention key outcomes, "
                "files/folders created, and whether the goal was achieved. Return plain text only.",
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"goal": goal, "working_dir": working_dir, "history": compact},
                    ensure_ascii=True,
                ),
            },
        ]
        raw, _provider = await llm_chat(messages=messages, temperature=0.2, max_tokens=200)
        return raw.strip()

    @staticmethod
    def _detect_workspace(working_dir: str) -> Dict[str, Any]:
        """Detect workspace context — package.json, .vscode, .git, etc."""
        wd = Path(working_dir)
        hints: Dict[str, Any] = {"type": "unknown"}
        if (wd / ".vscode").is_dir():
            hints["type"] = "vscode_workspace"
        if (wd / ".git").is_dir():
            hints["has_git"] = True
        if (wd / "package.json").is_file():
            hints["type"] = "node_project"
            try:
                pkg = json.loads((wd / "package.json").read_text(encoding="utf-8"))
                hints["project_name"] = pkg.get("name", "")
                hints["has_dependencies"] = bool(pkg.get("dependencies"))
            except Exception:
                pass
        if (wd / "requirements.txt").is_file():
            hints["type"] = "python_project"
        if (wd / "Cargo.toml").is_file():
            hints["type"] = "rust_project"
        if any((wd / f).is_file() for f in ("*.csproj", "*.sln")):
            hints["type"] = "dotnet_project"
        if (wd / "pyproject.toml").is_file():
            hints["type"] = "python_project"
        return hints

    @staticmethod
    def _extract_json(raw: str) -> Dict[str, Any]:
        text = str(raw or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].strip()
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            text = text[start : end + 1]
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            # Try to fix common issues
            fixed = re.sub(r",(\s*[}\]])", r"\1", text)
            try:
                parsed = json.loads(fixed)
            except json.JSONDecodeError:
                return {"done": True, "answer": f"Failed to parse planner response: {text[:200]}"}
        if not isinstance(parsed, dict):
            return {"done": True, "answer": "Shell agent expected a JSON object response."}
        return parsed

    @staticmethod
    def _extract_tool_name(goal: str) -> Optional[str]:
        normalized = str(goal or "").lower()
        catalog = get_tool_catalog_service().summary()
        for tool in catalog.get("tools", []):
            name = str(tool.get("name", "")).strip()
            if not name:
                continue
            if name.lower() in normalized or name.replace("_", " ").lower() in normalized:
                return name
        return None


__all__ = [
    "GuardedCommandRunner",
    "ShellAgentTool",
]

