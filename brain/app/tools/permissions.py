"""Permission engine (REDESIGN §7.2, §20.6), Claude Code style. Precedence is deny → ask → allow
across every matching rule; with no rule, the mode decides by risk. `review` means the auto-reviewer
gets a say (medium-risk writes in default mode). MCP annotations count only for trusted servers.
"""

from __future__ import annotations

import fnmatch
import glob
import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.runtime import Runtime
from app.db.models import PermissionRule
from app.tools.spec import Risk, ToolSpec

Decision = Literal["allow", "ask", "deny"]
Verdict = Literal["allow", "ask", "deny", "review"]
Mode = Literal["default", "ask", "trust"]


@dataclass(frozen=True)
class Rule:
    tool: str
    decision: Decision
    pattern: str = ""  # glob on the tool's matched field; '' = every input
    device_id: uuid.UUID | None = None  # None = every device of the user


# Read-only PowerShell / cmd commands that never change anything: no chaining, redirection,
# pipes into other commands, or subexpressions. Anything else in shell_run asks.
# ponytail: a small allowlist; a parser-based classifier if users hit asks on harmless commands
_SAFE_SHELL = re.compile(
    r"^\s*(?:dir|ls|gci|get-childitem|get-content|cat|type|echo|write-output|whoami|hostname|"
    r"ipconfig|systeminfo|get-process|ps|get-date|get-location|pwd|test-path|get-psdrive|"
    r"get-computerinfo|get-volume|git\s+(?:status|log|diff|branch))\b[^;&|<>`$()]*$",
    re.IGNORECASE,
)


def _norm(value: str) -> str:
    # Windows paths and app names are case-insensitive; patterns use forward slashes
    return value.replace("\\", "/").lower()


def matches(rule: Rule, spec: ToolSpec, value: str, device_id: uuid.UUID | None) -> bool:
    if rule.tool != spec.name:
        return False
    if rule.device_id is not None and rule.device_id != device_id:
        return False
    return not rule.pattern or fnmatch.fnmatchcase(_norm(value), _norm(rule.pattern))


def effective_risk(spec: ToolSpec, inp: dict[str, Any]) -> Risk:
    if spec.name == "shell_run" and _SAFE_SHELL.match(str(inp.get("command", ""))):
        return Risk.READ
    return spec.risk


def decide(
    spec: ToolSpec,
    inp: dict[str, Any],
    *,
    mode: str,
    rules: Sequence[Rule],
    device_id: uuid.UUID | None = None,
) -> Verdict:
    value = spec.matched(inp)
    hits = {r.decision for r in rules if matches(r, spec, value, device_id)}
    for decision in ("deny", "ask", "allow"):
        if decision in hits:
            return decision
    if spec.mcp_server and not spec.mcp_trusted:
        return "ask"  # untrusted servers' annotations (readOnlyHint…) are ignored (T5)
    risk = effective_risk(spec, inp)
    if mode == "ask":
        return "ask"
    if mode == "trust":
        return "allow"  # purchases and payments always ask; no tool buys anything yet
    if risk is Risk.READ:
        return "allow"
    if risk is Risk.WRITE:
        return "review" if spec.review else "allow"
    return "ask"  # destructive and external


def hidden(rules: Iterable[Rule]) -> set[str]:
    """A bare-tool deny for every device removes the tool from the model's context (§20.6)."""
    return {r.tool for r in rules if r.decision == "deny" and not r.pattern and r.device_id is None}


async def load_db(db: AsyncSession, user_id: uuid.UUID) -> list[Rule]:
    rows = await db.scalars(select(PermissionRule).where(PermissionRule.user_id == user_id))
    return [
        Rule(r.tool, r.decision, r.pattern, r.device_id)  # type: ignore[arg-type]
        for r in rows
    ]


async def load(rt: Runtime, user_id: uuid.UUID) -> list[Rule]:
    async with rt.db() as db:
        return await load_db(db, user_id)


async def always_allow(
    rt: Runtime, user_id: uuid.UUID, spec: ToolSpec, inp: dict[str, Any]
) -> None:
    """'Always allow' adds an allow rule for exactly this input (the tool's matched field)."""
    async with rt.db() as db:
        db.add(
            PermissionRule(
                user_id=user_id,
                tool=spec.name,
                pattern=glob.escape(spec.matched(inp)),  # literal: "a[1].txt" is not a class
                decision="allow",
            )
        )
        await db.commit()
