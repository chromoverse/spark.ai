"""
Tool Execution Logger — Detailed live logging for tool internals.

Tools import this to emit structured logs visible in the Spark UI.
Logs: params received, internal LLM calls, shell commands, outputs.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional

from app.socket.log_stream import emit_spark_log

logger = logging.getLogger(__name__)


class ToolLogger:
    """
    Per-execution logger for a tool. Emits structured events to the live log stream.

    Usage inside a tool:
        from app.utils.tool_logger import ToolLogger

        tl = ToolLogger(user_id, task_id, "folder_organize")
        await tl.log_params({"path": "/Desktop", "mode": "auto"})
        await tl.log_llm_call("categorize files", model="llama-3.1-8b", tokens=150)
        await tl.log_shell("dir /b C:\\Users\\Desktop", exit_code=0, output="file1.txt\nfile2.pdf")
        await tl.log_step("Moving 5 files to 3 folders")
        await tl.log_output(success=True, data={"moved": 5, "folders": 3})
    """

    def __init__(self, user_id: str, task_id: str, tool_name: str):
        self.user_id = user_id
        self.task_id = task_id
        self.tool_name = tool_name
        self._start = time.perf_counter()

    async def log_params(self, params: Dict[str, Any]) -> None:
        """Log the resolved input parameters the tool received."""
        # Truncate large values for display
        display = {k: _truncate(v) for k, v in params.items() if not k.startswith("_")}
        await self._emit("tool_params", params=display)

    async def log_llm_call(self, purpose: str, model: str = "", tokens: int = 0, duration_ms: int = 0) -> None:
        """Log an internal LLM call made by the tool."""
        await self._emit("tool_llm_call", purpose=purpose, model=model, tokens=tokens, duration_ms=duration_ms)

    async def log_shell(self, command: str, exit_code: int = 0, output: str = "") -> None:
        """Log a shell command executed by the tool."""
        await self._emit("tool_shell", command=command, exit_code=exit_code, output=_truncate(output, 500))

    async def log_step(self, message: str) -> None:
        """Log a progress step within the tool."""
        await self._emit("tool_step", message=message)

    async def log_output(self, success: bool, data: Any = None, error: str = "") -> None:
        """Log the final tool output."""
        elapsed = int((time.perf_counter() - self._start) * 1000)
        await self._emit("tool_output", success=success, data=_truncate(data, 1000), error=error, duration_ms=elapsed)

    async def _emit(self, event_type: str, **kwargs) -> None:
        try:
            await emit_spark_log(
                self.user_id, event_type,
                task_id=self.task_id,
                tool_name=self.tool_name,
                payload=kwargs,
            )
        except Exception:
            pass  # never break tool execution for logging


def _truncate(value: Any, max_len: int = 200) -> Any:
    """Truncate strings/dicts for display."""
    if isinstance(value, str) and len(value) > max_len:
        return value[:max_len] + "..."
    if isinstance(value, dict):
        return {k: _truncate(v, max_len) for k, v in list(value.items())[:10]}
    if isinstance(value, list) and len(value) > 10:
        return value[:10] + [f"...+{len(value)-10} more"]
    return value
