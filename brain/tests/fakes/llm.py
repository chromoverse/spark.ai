"""Scriptable OpenAI-compatible LLM (TESTING.md §2). Plug `handle` into httpx.MockTransport;
R1's openai_compat adapter talks to it exactly like Groq/NVIDIA/OpenRouter."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.clock import Clock


@dataclass
class Turn:
    text: list[str] = field(default_factory=list)  # content deltas, in order
    tool_calls: list[dict[str, Any]] = field(default_factory=list)  # {"name", "arguments"}
    ttft_s: float = 0.0  # delay before the first delta
    gap_s: float = 0.0  # delay between deltas (stall tests use a big one)
    status: int = 200  # 429 / 5xx return an error body instead of a stream
    retry_after_s: int | None = None
    malformed: bool = False  # tool call arguments that aren't valid JSON
    # fields of a last chunk: {"usage": …} (OpenAI style) or {"x_groq": {"usage": …}} (Groq)
    last_chunk: dict[str, Any] | None = None


class FakeProvider:
    def __init__(self, clock: Clock | None = None, model: str = "fake-model") -> None:
        self.clock = clock or Clock()
        self.model = model
        self.script: deque[Turn] = deque()
        self.scripts: dict[str, deque[Turn]] = {}  # per model: agent, reviewer, reflex turns
        self.requests: list[dict[str, Any]] = []
        self.request_times: list[float] = []  # clock.monotonic() when each request arrived

    def queue(self, *turns: Turn, model: str | None = None) -> None:
        """Turns for any request, or only for requests naming `model`."""
        if model is None:
            self.script.extend(turns)
        else:
            self.scripts.setdefault(model, deque()).extend(turns)

    def for_model(self, model: str) -> list[dict[str, Any]]:
        return [r for r in self.requests if r.get("model") == model]

    async def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions"), request.url
        body = json.loads(request.content)
        self.requests.append(body)
        self.request_times.append(self.clock.monotonic())
        script = self.scripts.get(body.get("model", ""), self.script)
        turn = script.popleft() if script else Turn(text=["Sure."])
        if turn.status != 200:
            headers = {"retry-after": str(turn.retry_after_s)} if turn.retry_after_s else {}
            return httpx.Response(
                turn.status,
                headers=headers,
                json={"error": {"message": "fake provider error", "code": turn.status}},
            )
        if not body.get("stream"):
            raise AssertionError("FakeProvider only serves streaming requests")
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=self._sse(turn)
        )

    def _chunk(self, delta: dict[str, Any], finish: str | None = None) -> bytes:
        payload = {
            "id": "chatcmpl-fake",
            "object": "chat.completion.chunk",
            "model": self.model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        return f"data: {json.dumps(payload)}\n\n".encode()

    async def _sse(self, turn: Turn) -> AsyncIterator[bytes]:
        await self.clock.sleep(turn.ttft_s)
        for i, text in enumerate(turn.text):
            if i:
                await self.clock.sleep(turn.gap_s)
            yield self._chunk({"content": text})
        for i, call in enumerate(turn.tool_calls):
            args = '{"broken": ' if turn.malformed else json.dumps(call["arguments"])
            yield self._chunk(
                {
                    "tool_calls": [
                        {
                            "index": i,
                            "id": f"call_{i}",
                            "type": "function",
                            "function": {"name": call["name"], "arguments": args},
                        }
                    ]
                }
            )
        yield self._chunk({}, "tool_calls" if turn.tool_calls else "stop")
        if turn.last_chunk is not None:
            last = {"id": "chatcmpl-fake", "choices": [], **turn.last_chunk}
            yield f"data: {json.dumps(last)}\n\n".encode()
        yield b"data: [DONE]\n\n"
