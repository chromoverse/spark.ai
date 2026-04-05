"""Bounded shell agent tooling.

shell_agent:
- Purpose: let the LLM inspect tool/path context, plan one safe shell step at a
  time, and stop only when the task is complete or blocked.
- Inputs: goal (required), working_dir?, max_steps?, allow_network?
- Output: final_answer, steps, step_count, working_dir, completed_at.

GuardedCommandRunner:
- Purpose: classify commands as read-only, mutating, destructive, or blocked.
- Safety: mutating/destructive commands require approval; blocked commands fail closed.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
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
    "git clone",
    "winget ",
    "choco ",
    "scoop ",
    "test-netconnection",
    "ping ",
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
    "set-content",
    "rename-item",
    "ren ",
    "move-item",
    "taskkill",
    "stop-process",
    "shutdown",
    "restart-computer",
    "git clean",
    "git reset",
)

_MUTATING_PATTERNS = _DESTRUCTIVE_PATTERNS + (
    "copy-item",
    "new-item",
    "mkdir",
    "md ",
    "out-file",
    "add-content",
    "set-location",
    "cd ",
    "push-location",
    "pop-location",
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
        if decision["requires_approval"]:
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

        result = self._execute_command(command=command, working_dir=working_dir)
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
                "reason": "Empty command.",
                "approval_question": "",
            }

        if any(pattern in normalized for pattern in _NETWORK_PATTERNS) and not allow_network:
            return {
                "blocked": True,
                "requires_approval": False,
                "is_read_only": False,
                "destructive": False,
                "reason": "Networked commands are blocked unless allow_network=true.",
                "approval_question": "",
            }

        is_read_only = normalized.startswith(_READ_ONLY_PREFIXES)
        destructive = any(pattern in normalized for pattern in _DESTRUCTIVE_PATTERNS)
        mutating = destructive or any(pattern in normalized for pattern in _MUTATING_PATTERNS)
        requires_approval = not is_read_only or mutating
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
            "reason": "Read-only command." if is_read_only else "Mutating or unclassified command.",
            "approval_question": approval_question,
        }

    def _execute_command(self, *, command: str, working_dir: str) -> Dict[str, Any]:
        cwd = str(Path(working_dir).expanduser().resolve())
        if sys.platform == "win32":
            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
        else:
            cmd = ["bash", "-lc", command]

        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return {
            "stdout": (result.stdout or "")[:6000],
            "stderr": (result.stderr or "")[:4000],
            "exit_code": int(result.returncode),
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
            return False
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
            return False


class ShellAgentTool(BaseTool):
    """Run a multi-step shell workflow with LLM planning and approval gates.

    Params:
    - goal: required natural-language task for the shell agent to complete.
    - working_dir: optional starting directory for command execution.
    - max_steps: optional step limit. Clamped to a safe range.
    - allow_network: allow networked commands when true.
    - user_id: optional explicit user id. Usually injected by the runtime.
    - _task_id: optional runtime task id used for approval prompts and tracing.

    Output:
    - final_answer: plain-language summary of the run.
    - steps: per-step planning and execution records.
    - step_count: number of executed steps.
    - working_dir: resolved execution directory.
    - completed_at: ISO timestamp marking the end of the run.
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
        max_steps = max(1, min(8, int(self.get_input(inputs, "max_steps", 6) or 6)))
        allow_network = bool(self.get_input(inputs, "allow_network", False))
        user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "guest").strip() or "guest"
        task_id = str(inputs.get("_task_id") or "shell_agent").strip() or "shell_agent"

        history: List[Dict[str, Any]] = []
        for step_index in range(1, max_steps + 1):
            # Each loop asks the LLM for one bounded next step, then feeds the
            # execution result back into the following planning round.
            decision = await self._plan_next_step(
                goal=goal,
                working_dir=working_dir,
                history=history,
                step_index=step_index,
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
                    }
                )

            command = str(decision.get("command", "")).strip()
            if not command:
                return ToolOutput(success=False, data={"steps": history}, error="Shell agent returned no command.")

            result = await self.command_runner.run(
                command=command,
                working_dir=working_dir,
                user_id=user_id,
                task_id=task_id,
                step_index=step_index,
                allow_network=allow_network,
            )
            history.append(
                {
                    "step": step_index,
                    "reason": str(decision.get("reason", "")).strip(),
                    "command": command,
                    **result,
                }
            )
            if not result.get("allowed"):
                return ToolOutput(
                    success=False,
                    data={
                        "final_answer": "I stopped because the command was blocked or not approved.",
                        "steps": history,
                        "step_count": len(history),
                        "working_dir": working_dir,
                        "completed_at": datetime.now().isoformat(),
                    },
                    error=result.get("stderr") or "Shell command was not allowed.",
                )

        final_answer = await self._summarize_run(goal=goal, working_dir=working_dir, history=history)
        return ToolOutput(
            success=False,
            data={
                "final_answer": final_answer,
                "steps": history,
                "step_count": len(history),
                "working_dir": working_dir,
                "completed_at": datetime.now().isoformat(),
            },
            error="Shell agent reached the maximum number of steps before confirming completion.",
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
        prompt = {
            "goal": goal,
            "working_dir": working_dir,
            "step_index": step_index,
            "path_context": path_context,
            "tool_catalog_context": catalog_context,
            "history": history,
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a safe shell planning agent. "
                    "Return ONLY JSON with keys: done, answer, command, reason. "
                    "If the task can be answered from the provided tool/path context, set done=true and provide answer. "
                    "If a command is needed, set done=false and provide exactly one bounded PowerShell command. "
                    "Prefer inspection before mutation. Never emit markdown."
                ),
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=True)},
        ]
        raw, _provider = await llm_chat(messages=messages, temperature=0.1, max_tokens=400)
        return self._extract_json(raw)

    async def _summarize_run(self, *, goal: str, working_dir: str, history: List[Dict[str, Any]]) -> str:
        from app.ai.providers import llm_chat

        messages = [
            {
                "role": "system",
                "content": "Summarize the shell run in 1-3 concise sentences. Return plain text only.",
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "goal": goal,
                        "working_dir": working_dir,
                        "history": history,
                    },
                    ensure_ascii=True,
                ),
            },
        ]
        raw, _provider = await llm_chat(messages=messages, temperature=0.2, max_tokens=120)
        return raw.strip()

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
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("Shell agent expected a JSON object response.")
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
