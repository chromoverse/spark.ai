"""OpenAI-compatible adapter (REDESIGN §5.4): Groq, NVIDIA, Cloudflare Workers AI, Mistral, Gemini,
OpenRouter, and the device's llama.cpp server. Streams chat completions over the shared httpx
client and normalizes them to `StreamEvent`s and content blocks."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Sequence
from typing import Any

import httpx

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
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
    "content_filter": "refusal",
}


def to_openai(system: str, messages: Sequence[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"role": "system", "content": system}] if system else []
    for msg in messages:
        blocks = msg["content"]
        if isinstance(blocks, str):
            out.append({"role": msg["role"], "content": blocks})
            continue
        text = "".join(b["text"] for b in blocks if b["type"] == "text")
        if msg["role"] == "assistant":
            calls = [
                {
                    "id": b["id"],
                    "type": "function",
                    "function": {"name": b["name"], "arguments": json.dumps(b["input"])},
                }
                for b in blocks
                if b["type"] == "tool_use"
            ]
            entry: dict[str, Any] = {"role": "assistant", "content": text or None}
            if calls:
                entry["tool_calls"] = calls
            out.append(entry)
            continue
        for b in blocks:
            if b["type"] == "tool_result":
                content = b["content"]
                if b.get("is_error"):
                    content = f"ERROR: {content}"
                out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": content})
        if text:
            out.append({"role": "user", "content": text})
    return out


def _error(r: httpx.Response) -> ProviderError:
    if r.status_code == 429:
        retry = r.headers.get("retry-after")
        try:
            retry_s = float(retry) if retry else None
        except ValueError:
            retry_s = None
        return ProviderError("rate_limited", "429", retry_s)
    if r.status_code >= 500:
        return ProviderError("unavailable", str(r.status_code))
    # 400/401/403/404/422: bad key, model gone, or a request this provider won't take.
    return ProviderError("rejected", str(r.status_code))


async def stream(
    http: httpx.AsyncClient,
    *,
    base_url: str,
    api_key: str,
    model: str,
    system: str,
    messages: Sequence[Message],
    tools: Sequence[ToolDef] = (),
    max_tokens: int = 512,
    extra: dict[str, Any] | None = None,
) -> AsyncGenerator[StreamEvent, None]:
    body: dict[str, Any] = {
        "model": model,
        "stream": True,
        "messages": to_openai(system, messages),
        "max_tokens": max_tokens,
        **(extra or {}),
    }
    if tools:
        body["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in tools
        ]
        body["tool_choice"] = "auto"
    calls: dict[int, dict[str, str]] = {}
    finish = "stop"
    usage: dict[str, int] = {}
    try:
        async with http.stream(
            "POST",
            f"{base_url}/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {api_key}"},
        ) as r:
            if r.status_code != 200:
                await r.aread()
                raise _error(r)
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                if u := chunk.get("usage"):
                    usage = {
                        "input_tokens": int(u.get("prompt_tokens") or 0),
                        "output_tokens": int(u.get("completion_tokens") or 0),
                    }
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    if text := delta.get("content"):
                        yield TextDelta(text)
                    for tc in delta.get("tool_calls") or []:
                        slot = calls.setdefault(tc.get("index", 0), {"id": "", "name": "", "a": ""})
                        fn = tc.get("function") or {}
                        slot["id"] = tc.get("id") or slot["id"]
                        slot["name"] = fn.get("name") or slot["name"]
                        slot["a"] += fn.get("arguments") or ""
                    finish = choice.get("finish_reason") or finish
    except httpx.TimeoutException:
        raise ProviderError("timeout") from None
    except (httpx.TransportError, json.JSONDecodeError) as exc:
        raise ProviderError("unavailable", type(exc).__name__) from None

    allowed = {t.name for t in tools}
    for i in sorted(calls):
        slot = calls[i]
        try:
            args = json.loads(slot["a"] or "{}")
        except json.JSONDecodeError:
            raise ProviderError("malformed", f"bad arguments for {slot['name']}") from None
        if slot["name"] not in allowed or not isinstance(args, dict):
            raise ProviderError("malformed", f"unknown tool {slot['name']!r}")
        yield ToolUse(slot["id"] or f"call_{i}", slot["name"], args)
    yield Done("tool_use" if calls else _STOP.get(finish, "end_turn"), usage)
