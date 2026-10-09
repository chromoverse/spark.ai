"""Provider-neutral stream events. Messages are Anthropic-style content blocks (REDESIGN §5.2):
{"role": "user"|"assistant", "content": [{"type": "text"|"tool_use"|"tool_result", ...}]}.
Adapters convert them to their provider's wire format."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Message = dict[str, Any]
StopReason = Literal["end_turn", "tool_use", "max_tokens", "refusal"]
ErrorKind = Literal["rate_limited", "unavailable", "timeout", "stalled", "malformed", "rejected"]


@dataclass(frozen=True)
class ToolDef:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ToolUse:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class Done:
    stop: StopReason
    usage: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Restart:
    """The stream broke after it had produced output and the next chain entry starts over.
    Consumers drop anything unspoken and play a bridge cue (REDESIGN §19.2)."""

    reason: ErrorKind


StreamEvent = TextDelta | ToolUse | Done | Restart


class ProviderError(Exception):
    """A chain entry failed. `kind` drives the fallthrough and the circuit breaker."""

    def __init__(self, kind: ErrorKind, detail: str = "", retry_after_s: float | None = None):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind
        self.retry_after_s = retry_after_s


class ChainExhausted(Exception):
    """No entry in the chain could answer. Callers explain it to the user, never go silent."""
