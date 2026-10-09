"""Self-check for the FakeProvider so R1's chain tests can trust it. No DB needed."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from tests.fakes.clock import FakeClock
from tests.fakes.llm import FakeProvider, Turn

URL = "https://api.groq.test/openai/v1/chat/completions"


async def _stream(provider: FakeProvider) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider.handle)) as client:
        body = {"model": "x", "stream": True, "messages": [{"role": "user", "content": "hi"}]}
        async with client.stream("POST", URL, json=body) as r:
            r.raise_for_status()
            chunks = []
            async for line in r.aiter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    chunks.append(json.loads(line[6:]))
            return chunks


async def test_streams_scripted_text_and_records_requests() -> None:
    p = FakeProvider()
    p.queue(Turn(text=["Hey, ", "it's ", "nine."]))
    chunks = await _stream(p)
    text = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks)
    assert text == "Hey, it's nine."
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    assert p.requests[0]["messages"][0]["content"] == "hi"


async def test_ttft_runs_on_the_controllable_clock() -> None:
    clock = FakeClock()
    p = FakeProvider(clock)
    p.queue(Turn(text=["late"], ttft_s=0.6))
    task = asyncio.create_task(_stream(p))
    await asyncio.sleep(0.05)
    assert not task.done()  # nothing arrives until simulated time passes
    clock.advance(0.6)
    assert (await asyncio.wait_for(task, 2))[0]["choices"][0]["delta"]["content"] == "late"


async def test_errors_and_malformed_tool_calls() -> None:
    p = FakeProvider()
    p.queue(
        Turn(status=429, retry_after_s=12),
        Turn(tool_calls=[{"name": "app_open", "arguments": {"app": "spotify"}}], malformed=True),
        Turn(),
    )
    with pytest.raises(httpx.HTTPStatusError) as err:
        await _stream(p)
    assert err.value.response.status_code == 429
    assert err.value.response.headers["retry-after"] == "12"

    chunks = await _stream(p)
    call = chunks[0]["choices"][0]["delta"]["tool_calls"][0]["function"]
    assert call["name"] == "app_open"
    with pytest.raises(json.JSONDecodeError):
        json.loads(call["arguments"])
    assert chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"

    empty = await _stream(p)
    assert [c["choices"][0]["delta"] for c in empty] == [{}]
