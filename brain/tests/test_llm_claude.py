"""Anthropic adapter (paid, off during the build): stream mapping, tool calls, errors, and that
the chain only offers it when paid providers are on. No network: the SDK client is faked."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest
from redis.asyncio import Redis

from app.llm import claude
from app.llm.chains import CHAINS, ChainRunner
from app.llm.types import Done, ProviderError, StreamEvent, TextDelta, ToolDef, ToolUse
from tests.conftest import TEST_REDIS, make_settings
from tests.fakes.clock import FakeClock


class FakeStream:
    def __init__(self, texts: list[str], final: Any, exc: Exception | None = None) -> None:
        self.texts, self.final, self.exc = texts, final, exc

    async def __aenter__(self) -> FakeStream:
        if self.exc:
            raise self.exc
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def __aiter__(self) -> AsyncIterator[Any]:
        for t in self.texts:
            yield SimpleNamespace(type="text", text=t)

    async def get_final_message(self) -> Any:
        return self.final


class FakeApi:
    def __init__(self, stream: FakeStream) -> None:
        self.params: list[dict[str, Any]] = []
        self.messages = SimpleNamespace(stream=self._stream)
        self._s = stream

    def _stream(self, **params: Any) -> FakeStream:
        self.params.append(params)
        return self._s


def final(*blocks: Any, stop: str = "end_turn") -> Any:
    usage = SimpleNamespace(input_tokens=12, output_tokens=5, cache_read_input_tokens=None)
    return SimpleNamespace(content=list(blocks), stop_reason=stop, usage=usage)


VOLUME = ToolDef("volume_set", "Sets volume", {"type": "object", "properties": {}})
HAIKU_EXTRA = {"thinking": {"type": "disabled"}, "output_config": {"effort": "low"}}


async def run(api: FakeApi, **kw: Any) -> list[StreamEvent]:
    msgs = [
        {"role": "user", "content": [{"type": "text", "text": "louder"}]},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": ""},
                {"type": "tool_use", "id": "t1", "name": "volume_set", "input": {}},
            ],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}],
        },
    ]
    return [
        ev
        async for ev in claude.stream(
            api,  # type: ignore[arg-type]
            model="claude-haiku-5-5",
            system="be brief",
            messages=msgs,
            tools=[VOLUME],
            extra=HAIKU_EXTRA,
            **kw,
        )
    ]


async def test_text_and_tool_calls_map_to_stream_events() -> None:
    use = SimpleNamespace(type="tool_use", id="toolu_1", name="volume_set", input={"level": 30})
    api = FakeApi(FakeStream(["Turning ", "it up."], final(use, stop="tool_use")))
    events = await run(api)
    assert [e.text for e in events if isinstance(e, TextDelta)] == ["Turning ", "it up."]
    assert [e for e in events if isinstance(e, ToolUse)] == [
        ToolUse("toolu_1", "volume_set", {"level": 30})
    ]
    done = events[-1]
    assert isinstance(done, Done) and done.stop == "tool_use"
    assert done.usage == {"input_tokens": 12, "output_tokens": 5, "cache_read_tokens": 0}
    sent = api.params[0]
    assert sent["thinking"] == {"type": "disabled"} and sent["output_config"] == {"effort": "low"}
    assert sent["messages"][1]["content"] == [
        {"type": "tool_use", "id": "t1", "name": "volume_set", "input": {}}
    ]  # the empty text block is dropped: the API rejects it
    assert sent["tools"][0]["name"] == "volume_set"


async def test_refusal_and_truncated_tool_input() -> None:
    events = await run(FakeApi(FakeStream([], final(stop="refusal"))))
    assert isinstance(events[-1], Done) and events[-1].stop == "refusal"
    cut = SimpleNamespace(type="tool_use", id="t", name="volume_set", input={"lev": 3})
    with pytest.raises(ProviderError) as err:
        await run(FakeApi(FakeStream([], final(cut, stop="max_tokens"))))
    assert err.value.kind == "malformed"


def _status(cls: type[anthropic.APIStatusError], status: int, headers: dict[str, str]) -> Exception:
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("nope", response=httpx2.Response(status, headers=headers, request=req), body=None)


@pytest.mark.parametrize(
    ("exc", "kind", "retry"),
    [
        (_status(anthropic.RateLimitError, 429, {"retry-after": "30"}), "rate_limited", 30.0),
        (_status(anthropic.InternalServerError, 529, {}), "unavailable", None),
        (_status(anthropic.AuthenticationError, 401, {}), "rejected", None),
    ],
)
async def test_sdk_errors_become_chain_errors(
    exc: Exception, kind: str, retry: float | None
) -> None:
    with pytest.raises(ProviderError) as err:
        await run(FakeApi(FakeStream([], None, exc)))
    assert err.value.kind == kind and err.value.retry_after_s == retry


async def test_chain_offers_claude_only_when_paid_is_on() -> None:
    redis = Redis.from_url(TEST_REDIS, decode_responses=True)
    clock = FakeClock()
    try:
        off = ChainRunner(make_settings(anthropic_api_key="sk-ant-x"), clock, None, redis)  # type: ignore[arg-type]
        on = ChainRunner(
            make_settings(anthropic_api_key="sk-ant-x", paid_providers_enabled=True),
            clock,
            None,
            redis,  # type: ignore[arg-type]
        )
        assert CHAINS["reflex"][-1].model == "claude-haiku-5-5"
        assert "anthropic/claude-haiku-5-5" not in [
            c.label for c in await off.candidates("reflex", allow_training=False)
        ]
        assert [c.label for c in await on.candidates("reflex", allow_training=False)] == [
            "anthropic/claude-haiku-5-5"
        ]
    finally:
        await redis.aclose()
