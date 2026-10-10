"""shell_run (REDESIGN §7.3): one PowerShell command line with a timeout. Destructive by default in
the brain's permission engine; allow rules relax it. Output is capped so a chatty command can't
flood the model's context."""

from __future__ import annotations

import subprocess
import sys
from typing import Any

from spark_body.hands.errors import ToolFailure
from spark_body.hands.files import resolve

OUTPUT_CHARS = 8000


def _cap(text: str) -> str:
    return text if len(text) <= OUTPUT_CHARS else text[:OUTPUT_CHARS] + "\n…[cut]"


def shell_run(inp: dict[str, Any]) -> dict[str, Any]:
    command = str(inp["command"])
    cwd = resolve(inp["cwd"]) if inp.get("cwd") else None
    if cwd is not None and not cwd.is_dir():
        raise ToolFailure("not_found", f"There's no folder at {cwd}.")
    timeout = int(inp.get("timeout_s", 30))
    if sys.platform == "win32":
        argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
    else:
        argv = ["sh", "-c", command]
    try:
        done = subprocess.run(  # noqa: S603 (the user's command, approved by the brain)
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise ToolFailure(
            "timeout", f"The command was still running after {timeout}s, so I stopped it."
        ) from None
    except FileNotFoundError:
        raise ToolFailure("unsupported", "There's no shell on this device.") from None
    return {"exit_code": done.returncode, "stdout": _cap(done.stdout), "stderr": _cap(done.stderr)}
