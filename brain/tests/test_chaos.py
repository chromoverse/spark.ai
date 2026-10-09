"""Chaos suite (TESTING.md §5, PHASES R1): 100 signals with random provider and tool failures.
Every one must end answered or explained, never silent. # proves §19.2 invariant"""

from __future__ import annotations

import random
from collections.abc import AsyncIterator

import pytest

from tests.conftest import Brain
from tests.fakes.clock import drive
from tests.fakes.device import FakeDevice
from tests.fakes.llm import Turn

pytestmark = pytest.mark.chaos

TOOL = {"name": "volume_change", "arguments": {"direction": "up"}}


def turn(rng: random.Random, failure_rate: float) -> Turn:
    if rng.random() >= failure_rate:
        if rng.random() < 0.25:
            return Turn(text=["Turning it up."], tool_calls=[TOOL])
        return Turn(text=["Sure, ", "here you go."])
    return rng.choice(
        [
            Turn(status=429, retry_after_s=1),
            Turn(status=503),
            Turn(text=["Well, ", "so"], gap_s=5),  # stalls after output
            Turn(text=[]),  # empty output
            Turn(text=["Late but fine."], ttft_s=0.6),  # hedge territory
            Turn(tool_calls=[TOOL], malformed=True),
        ]
    )


@pytest.fixture
async def laptop(brain: Brain) -> AsyncIterator[FakeDevice]:
    d = FakeDevice(brain.url, await brain.sign_in("asha@example.com", "Laptop"))
    await d.connect()
    await d.hello()
    yield d
    await d.close()


async def test_chaos_100_signals_none_silent(brain: Brain, laptop: FakeDevice) -> None:
    assert brain.groq is not None and brain.mistral is not None
    rng = random.Random(20261010)
    silent: list[int] = []
    explained = 0
    for i in range(100):
        # each signal meets fresh health so the failure mix, not open circuits, decides it
        async for key in brain.rt.redis.scan_iter("health:*"):
            await brain.rt.redis.delete(key)
        for fake in (brain.groq, brain.mistral):
            fake.script.clear()
            fake.queue(turn(rng, 0.2), turn(rng, 0.2))
        ok = rng.random() >= 0.2
        laptop.tools["volume_change"] = (
            {"ok": True, "output": {"level": 60}}
            if ok
            else {"ok": False, "error": {"code": "no_audio", "message": "No audio device."}}
        )
        sid, ack = await laptop.say(f"signal {i}")
        assert ack["ok"] is True
        deltas = await drive(brain.clock, laptop.reply(sid), step=0.05, limit_s=120)
        if not any(d["speak"] and d["text"] for d in deltas):
            silent.append(i)
        if any(d["tone"] == "serious" for d in deltas):
            explained += 1
    assert silent == []
    assert not brain.voice.sup.watches  # every watch reached a terminal state
    assert explained > 0  # the mix really hit the explain path
