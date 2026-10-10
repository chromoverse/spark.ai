"""Chain runner: free-first order, hedging, fallthrough, circuit breaker, stalls (REDESIGN §5.5,
§19). B2/S1/S6 rows run end to end in the scenario suite; these pin the runner's rules."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from redis.asyncio import Redis

from app.llm.chains import CHAINS, ChainRunner, Entry
from app.llm.types import ChainExhausted, Done, Restart, StreamEvent, TextDelta, ToolDef, ToolUse
from tests.conftest import TEST_REDIS, make_settings
from tests.fakes.clock import FakeClock, drive
from tests.fakes.llm import FakeProvider, Turn


class Providers:
    """FakeProviders by host, behind one httpx client like the brain's shared one."""

    def __init__(self, clock: FakeClock) -> None:
        self.by_host: dict[str, FakeProvider] = {}
        self.clock = clock
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(self._handle))

    def __getitem__(self, host: str) -> FakeProvider:
        return self.by_host.setdefault(host, FakeProvider(self.clock))

    async def _handle(self, request: httpx.Request) -> httpx.Response:
        return await self[request.url.host].handle(request)


@pytest.fixture
async def redis() -> AsyncIterator[Redis]:
    r = Redis.from_url(TEST_REDIS, decode_responses=True)
    await r.flushdb()
    yield r
    await r.aclose()


@pytest.fixture
def chain(monkeypatch: pytest.MonkeyPatch) -> list[Entry]:
    """Two free entries on different hosts, a training provider, and a paid one."""
    entries = [
        Entry("groq", "a"),
        Entry("mistral", "b"),
        Entry("gemini", "c", trains_on_data=True),
        Entry("anthropic", "d", paid=True),
    ]
    monkeypatch.setitem(CHAINS, "reflex", entries)
    return entries


GROQ, MISTRAL, GEMINI = "api.groq.com", "api.mistral.ai", "generativelanguage.googleapis.com"


def runner(redis: Redis, clock: FakeClock, providers: Providers, **settings: Any) -> ChainRunner:
    s = make_settings(
        groq_api_keys="gk1", mistral_api_keys="mk1", gemini_api_keys="gm1", **settings
    )
    return ChainRunner(s, clock, providers.http, redis)


async def collect(
    r: ChainRunner, clock: FakeClock, step: float = 0.01, **kw: Any
) -> list[StreamEvent]:
    async def consume() -> list[StreamEvent]:
        return [ev async for ev in r.stream("reflex", system="be brief", messages=[_hi()], **kw)]

    return await drive(clock, consume(), step)


def _hi() -> dict[str, Any]:
    return {"role": "user", "content": [{"type": "text", "text": "hi"}]}


def text(events: list[StreamEvent]) -> str:
    return "".join(e.text for e in events if isinstance(e, TextDelta))


async def test_first_free_entry_answers_and_health_records_ttft(
    redis: Redis, chain: list[Entry]
) -> None:
    clock = FakeClock()
    p = Providers(clock)
    p[GROQ].queue(Turn(text=["It's ", "nine."], ttft_s=0.2))
    r = runner(redis, clock, p)
    events = await collect(r, clock)
    assert text(events) == "It's nine."
    assert isinstance(events[-1], Done) and events[-1].stop == "end_turn"
    assert len(p[MISTRAL].requests) == 0
    cand = (await r.candidates("reflex", allow_training=False))[0]
    assert 150 <= float((await r.health.snapshot(cand.hid))["ttft_ms"]) <= 300


async def test_paid_and_training_entries_are_filtered(redis: Redis, chain: list[Entry]) -> None:
    clock = FakeClock()
    p = Providers(clock)
    r = runner(redis, clock, p, anthropic_api_key="sk-x")
    labels = [c.label for c in await r.candidates("reflex", allow_training=False)]
    assert labels == ["groq/a", "mistral/b"]
    labels = [c.label for c in await r.candidates("reflex", allow_training=True)]
    assert labels == ["groq/a", "mistral/b", "gemini/c"]  # anthropic: paid is off


async def test_b2_hedge_at_350ms_second_stream_wins(redis: Redis, chain: list[Entry]) -> None:
    clock = FakeClock()
    p = Providers(clock)
    p[GROQ].queue(Turn(text=["slow"], ttft_s=0.6))
    p[MISTRAL].queue(Turn(text=["fast"], ttft_s=0.1))
    events = await collect(runner(redis, clock, p), clock)
    assert text(events) == "fast"
    assert len(p[GROQ].requests) == 1 and len(p[MISTRAL].requests) == 1
    # the hedge starts 350 ms after the first request, not after the slow 600 ms
    hedge_at = p[MISTRAL].request_times[0] - p[GROQ].request_times[0]
    assert 0.35 <= hedge_at < 0.45


async def test_b2_hedge_waits_for_late_by_this_entrys_usual(
    redis: Redis, chain: list[Entry]
) -> None:
    """From Nepal Groq's first token usually takes ~450 ms: a 350 ms hedge doubled every call.
    The hedge fires when the entry is late for itself (1.3 x its usual), 350 ms at the least."""
    clock = FakeClock()
    p = Providers(clock)
    r = runner(redis, clock, p)
    groq = (await r.candidates("reflex", allow_training=False))[0]
    await r.health.ok(groq.hid, 450.0)  # its usual
    p[GROQ].queue(Turn(text=["hi"], ttft_s=0.5))
    assert text(await collect(r, clock)) == "hi"
    assert len(p[MISTRAL].requests) == 0  # ~500 ms is normal for it: no hedge
    p[GROQ].queue(Turn(text=["slow"], ttft_s=2.0))
    p[MISTRAL].queue(Turn(text=["fast"], ttft_s=0.1))
    assert text(await collect(r, clock)) == "fast"
    hedge_at = p[MISTRAL].request_times[0] - p[GROQ].request_times[-1]
    assert 0.58 <= hedge_at < 0.65  # 1.3 x 0.45 s


async def test_s6_rate_limit_falls_through_and_cools_down(redis: Redis, chain: list[Entry]) -> None:
    clock = FakeClock()
    p = Providers(clock)
    p[GROQ].queue(Turn(status=429, retry_after_s=3600))
    p[MISTRAL].queue(Turn(text=["one"]), Turn(text=["two"]))
    r = runner(redis, clock, p)
    assert text(await collect(r, clock)) == "one"
    assert text(await collect(r, clock)) == "two"
    assert len(p[GROQ].requests) == 1  # circuit open until the quota resets
    clock.advance(3601)
    p[GROQ].queue(Turn(text=["back"]))
    assert text(await collect(r, clock)) == "back"


async def test_s1_stall_mid_stream_restarts_on_next_entry(redis: Redis, chain: list[Entry]) -> None:
    clock = FakeClock()
    p = Providers(clock)
    p[GROQ].queue(Turn(text=["Sure, ", "so"], gap_s=5))
    p[MISTRAL].queue(Turn(text=["Here's the answer."]))
    events = await collect(runner(redis, clock, p), clock, step=0.05)
    kinds = [type(e).__name__ for e in events]
    assert kinds[:2] == ["TextDelta", "Restart"]
    assert isinstance(events[1], Restart) and events[1].reason == "stalled"
    assert text(events[2:]) == "Here's the answer."


async def test_empty_output_and_malformed_tool_calls_fall_through(
    redis: Redis, chain: list[Entry]
) -> None:
    clock = FakeClock()
    p = Providers(clock)
    tool = ToolDef("volume_set", "Sets volume", {"type": "object", "properties": {}})
    p[GROQ].queue(
        Turn(text=[]),
        Turn(tool_calls=[{"name": "volume_set", "arguments": {}}], malformed=True),
    )
    p[MISTRAL].queue(
        Turn(text=["Ok."]),
        Turn(tool_calls=[{"name": "volume_set", "arguments": {"level": 30}}]),
    )
    r = runner(redis, clock, p)
    assert text(await collect(r, clock, tools=[tool])) == "Ok."
    events = await collect(r, clock, tools=[tool])
    uses = [e for e in events if isinstance(e, ToolUse)]
    assert [(u.name, u.input) for u in uses] == [("volume_set", {"level": 30})]
    assert isinstance(events[-1], Done) and events[-1].stop == "tool_use"


async def test_every_entry_failing_raises_chain_exhausted(redis: Redis, chain: list[Entry]) -> None:
    clock = FakeClock()
    p = Providers(clock)
    p[GROQ].queue(Turn(status=503))
    p[MISTRAL].queue(Turn(text=["x"], ttft_s=10))
    with pytest.raises(ChainExhausted):
        await collect(runner(redis, clock, p), clock, step=0.05)


async def test_no_keys_means_no_candidates(redis: Redis, chain: list[Entry]) -> None:
    clock = FakeClock()
    r = ChainRunner(make_settings(), clock, Providers(clock).http, redis)
    with pytest.raises(ChainExhausted):
        await collect(r, clock)


def test_content_blocks_convert_to_openai_messages() -> None:
    from app.llm.openai_compat import to_openai

    msgs = [
        _hi(),
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Turning it up."},
                {"type": "tool_use", "id": "c1", "name": "volume_set", "input": {"level": 30}},
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "c1",
                    "content": "no speaker",
                    "is_error": True,
                }
            ],
        },
    ]
    assert to_openai("sys", msgs) == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "Turning it up.",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "volume_set", "arguments": '{"level": 30}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "ERROR: no speaker"},
    ]
