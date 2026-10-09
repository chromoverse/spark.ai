"""Anthropic adapter (REDESIGN §5.4) on the official SDK: paid chain entries, off during the build
(`PAID_PROVIDERS_ENABLED=false`). Messages are already Anthropic-style content blocks, so this
mostly maps the SDK's stream and errors onto the chain's `StreamEvent`s and `ProviderError`s.

The SDK runs on httpx2, so it keeps its own client instead of the brain's shared httpx one. Its
retries are off: the chain runner owns fallthrough, hedging, and health."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence
from typing import Any

import anthropic

from app.llm.types import (
    Done,
    Message,
    ProviderError,
    StopReason,
    StreamEvent,
    TextDelta,
    ToolDef,
    ToolUse,
)

_STOP: dict[str, StopReason] = {
    "end_turn": "end_turn",
    "stop_sequence": "end_turn",
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
    "refusal": "refusal",
}


def client(api_key: str) -> anthropic.AsyncAnthropic:
    """An explicit key only: never fall back to whatever credentials the host machine has."""
    return anthropic.AsyncAnthropic(api_key=api_key, max_retries=0, timeout=20.0)


def to_anthropic(messages: Sequence[Message]) -> list[dict[str, Any]]:
    """Our blocks are the API's blocks; empty text blocks (a turn that only called tools) are
    dropped because the API rejects them."""
    out: list[dict[str, Any]] = []
    for msg in messages:
        content = msg["content"]
        if isinstance(content, list):
            content = [b for b in content if not (b["type"] == "text" and not b.get("text"))]
        out.append({"role": msg["role"], "content": content})
    return out


def _error(exc: anthropic.APIError) -> ProviderError:
    if isinstance(exc, anthropic.RateLimitError):
        retry = exc.response.headers.get("retry-after")
        return ProviderError(
            "rate_limited", "429", float(retry) if retry and retry.isdigit() else None
        )
    if isinstance(exc, anthropic.APITimeoutError):
        return ProviderError("timeout")
    if isinstance(exc, anthropic.APIConnectionError):
        return ProviderError("unavailable", "connection")
    if isinstance(exc, anthropic.APIStatusError) and exc.status_code >= 500:
        return ProviderError("unavailable", str(exc.status_code))
    return ProviderError("rejected", type(exc).__name__)


async def stream(
    api: anthropic.AsyncAnthropic,
    *,
    model: str,
    system: str,
    messages: Sequence[Message],
    tools: Sequence[ToolDef] = (),
    max_tokens: int = 512,
    extra: dict[str, Any] | None = None,
) -> AsyncGenerator[StreamEvent, None]:
    params: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": to_anthropic(messages),
        **(extra or {}),
    }
    if tools:
        params["tools"] = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in tools
        ]
    try:
        async with api.messages.stream(**params) as s:
            async for event in s:
                if event.type == "text" and event.text:
                    yield TextDelta(event.text)
            final = await s.get_final_message()
    except anthropic.APIError as exc:
        raise _error(exc) from None
    except ValueError:
        # tool input JSON the SDK couldn't parse at all
        raise ProviderError("malformed", "unparseable tool input") from None

    allowed = {t.name for t in tools}
    uses = [b for b in final.content if b.type == "tool_use"]
    if uses and final.stop_reason == "max_tokens":
        raise ProviderError("malformed", "tool input cut off at max_tokens")
    for block in uses:
        if block.name not in allowed or not isinstance(block.input, dict):
            raise ProviderError("malformed", f"bad tool call {block.name!r}")
        yield ToolUse(block.id, block.name, block.input)
    usage = {
        "input_tokens": final.usage.input_tokens,
        "output_tokens": final.usage.output_tokens,
        "cache_read_tokens": final.usage.cache_read_input_tokens or 0,
    }
    yield Done(_STOP.get(final.stop_reason or "end_turn", "end_turn"), usage)
