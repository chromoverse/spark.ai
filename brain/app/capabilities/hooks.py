"""Tool hooks (REDESIGN §7.2, §20.5): plain async callables around every agent tool call.
`pre_tool` may deny or rewrite the input; `post_tool` may replace the result. Built-ins: secret
redaction (before the model, the step log, or anyone sees an output) and the audit log."""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.core.runtime import Runtime
from app.db.audit import audit
from app.tools.spec import Risk, ToolSpec

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Call:
    rt: Runtime
    user_id: uuid.UUID
    job_id: uuid.UUID | None
    device_id: uuid.UUID | None  # where it runs (None for brain tools)
    spec: ToolSpec
    input: dict[str, Any]


@dataclass(frozen=True)
class Outcome:
    ok: bool
    content: str  # what the model sees
    decision: str = "allow"


PreTool = Callable[[Call], Awaitable[dict[str, Any] | str | None]]  # new input | deny reason
PostTool = Callable[[Call, Outcome], Awaitable[Outcome | None]]

# API keys, bearer tokens, JWTs, private keys, and password assignments.
_SECRETS = re.compile(
    r"(?:sk|gsk|rk|pk|xox[abp]|ghp|gho|ghs|glpat)[-_][A-Za-z0-9_\-]{16,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|AIza[0-9A-Za-z_\-]{30,}"
    r"|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
    r"|(?i:bearer\s+)[A-Za-z0-9._\-]{20,}"
    r"|(?i:(?:password|passwd|pwd|secret|api[_-]?key|token)\s*[:=]\s*)\S{6,}"
)


def redact_text(text: str) -> str:
    return _SECRETS.sub("[redacted]", text)


async def redact(call: Call, out: Outcome) -> Outcome | None:
    clean = redact_text(out.content)
    return None if clean == out.content else Outcome(out.ok, clean, out.decision)


async def audit_hook(call: Call, out: Outcome) -> None:
    """Every call that can change something is audited: ids and the decision, never content."""
    if call.spec.risk is Risk.READ:
        return None
    try:
        async with call.rt.db() as db:
            audit(
                db,
                call.user_id,
                f"tool.{call.spec.name}",
                actor="system",
                target=str(call.device_id) if call.device_id else None,
                job_id=str(call.job_id) if call.job_id else None,
                decision=out.decision,
                ok=out.ok,
            )
            await db.commit()
    except Exception:
        logger.warning("audit row not written", exc_info=True)
    return None


PRE_TOOL: list[PreTool] = []
POST_TOOL: list[PostTool] = [redact, audit_hook]


async def before(call: Call) -> Call | str:
    """Runs pre_tool hooks: the (maybe rewritten) call, or a deny reason."""
    for hook in PRE_TOOL:
        result = await hook(call)
        if isinstance(result, str):
            return result
        if result is not None:
            call = Call(call.rt, call.user_id, call.job_id, call.device_id, call.spec, result)
    return call


async def after(call: Call, out: Outcome) -> Outcome:
    for hook in POST_TOOL:
        out = await hook(call, out) or out
    return out
