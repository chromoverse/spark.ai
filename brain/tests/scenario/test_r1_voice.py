"""R1 voice loop over the real gateway (TESTING.md §4.1, §4.5, §4.8, §4.9).
# proves §4.1, §4.4, §5.1, §19, §26.4-A/B/C, §27, PERSONA §4, §5"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app.db.models import Incident, Message
from app.llm.chains import ROLES, RoleConfig
from tests.conftest import Brain
from tests.fakes.clock import drive, until
from tests.fakes.device import FakeDevice
from tests.fakes.llm import Turn

pytestmark = pytest.mark.scenario


@pytest.fixture
async def laptop(brain: Brain) -> AsyncIterator[FakeDevice]:
    d = FakeDevice(brain.url, await brain.sign_in("asha@example.com", "Laptop"))
    await d.connect()
    await d.hello()
    yield d
    await d.close()


def spoken(deltas: list[dict[str, Any]]) -> list[str]:
    return [d["text"] for d in deltas if d["speak"]]


async def thread(
    brain: Brain, count: int | None = None
) -> list[tuple[str, list[dict[str, Any]], int | None]]:
    """Stored messages, oldest first. With `count`, waits for that many: a turn is stored
    after its last event reaches the device."""
    for _ in range(300):
        async with brain.rt.db() as db:
            rows = (await db.scalars(select(Message).order_by(Message.created_at))).all()
        if count is None or len(rows) >= count:
            break
        await asyncio.sleep(0.01)
    return [(m.role, m.content, m.tier) for m in rows]


async def incidents(brain: Brain, count: int = 1) -> list[Incident]:
    for _ in range(300):
        async with brain.rt.db() as db:
            rows = list((await db.scalars(select(Incident).order_by(Incident.ts))).all())
        if len(rows) >= count:
            break
        await asyncio.sleep(0.01)
    return rows


async def test_b1_conversation_streams_sentence_by_sentence(
    brain: Brain, laptop: FakeDevice
) -> None:
    assert brain.groq is not None and brain.mistral is not None
    brain.groq.queue(Turn(text=["It's a ", "good one. ", "Try Himalayan ", "Brew."], ttft_s=0.3))
    sid, ack = await laptop.say("what's a good name for a coffee shop", utc_offset_min=345)
    assert ack == {"ok": True, "data": {"signal_id": sid, "tier": 2}}

    await until(lambda: brain.groq.requests)
    brain.clock.advance(0.3)  # the fake TTFT; the brain adds no simulated time after it
    first = await laptop.next("reply.delta")
    rest = await laptop.reply(sid)
    assert spoken([first, *rest]) == ["It's a good one.", "Try Himalayan Brew."]
    assert rest[-1]["final"] is True and rest[-1]["text"] == ""

    # one reflex call, persona prompt, quick tools, volatile context last
    assert len(brain.groq.requests) == 1 and not brain.mistral.requests
    req = brain.groq.requests[0]
    assert "You are Spark" in req["messages"][0]["content"]
    assert {t["function"]["name"] for t in req["tools"]} >= {"volume_set", "app_open", "delegate"}
    last = req["messages"][-1]["content"]
    assert last.startswith("what's a good name") and "(context: it's " in last
    local = brain.clock.now() + timedelta(hours=5, minutes=45)  # Nepal, from utc_offset_min
    assert local.strftime("%I:%M %p").lstrip("0") + " local time" in last

    rows = await thread(brain, 2)
    assert [(r, t) for r, _, t in rows] == [("user", 2), ("assistant", 2)]
    assert rows[1][1] == [{"type": "text", "text": "It's a good one. Try Himalayan Brew."}]


async def test_b1_follow_up_carries_recent_turns(brain: Brain, laptop: FakeDevice) -> None:
    assert brain.groq is not None
    brain.groq.queue(Turn(text=["Kathmandu."]), Turn(text=["About a million people."]))
    sid, _ = await laptop.say("what's the capital of Nepal")
    await laptop.reply(sid)
    sid, _ = await laptop.say("how many people live there")
    assert spoken(await laptop.reply(sid)) == ["About a million people."]
    msgs = brain.groq.requests[1]["messages"]
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
    assert msgs[2]["content"] == "Kathmandu."


async def test_c1_speaks_and_acts_in_parallel_then_done_cue(
    brain: Brain, laptop: FakeDevice
) -> None:
    assert brain.groq is not None
    call = {"name": "media_play", "arguments": {"app": "spotify", "query": "something calm"}}
    brain.groq.queue(Turn(text=["Playing something calm on Spotify."], tool_calls=[call]))
    laptop.tools["media_play"] = {"ok": True, "output": {"playing": "Calm Vibes"}}
    sid, _ = await laptop.say("open spotify and play something calm")

    tool_call = await laptop.next("tool.call")
    assert tool_call["tool"] == "media_play" and tool_call["risk"] == "write"
    assert tool_call["input"] == {"app": "spotify", "query": "something calm"}
    deltas = await laptop.reply(sid)
    assert spoken(deltas) == ["Playing something calm on Spotify."]
    cue = await laptop.next("reply.cue")
    assert cue == cue | {"signal_id": sid, "kind": "done"}

    rows = await thread(brain, 3)
    assert [r for r, _, _ in rows] == ["user", "assistant", "user"]
    assert rows[1][1][1]["type"] == "tool_use" and rows[1][1][1]["name"] == "media_play"
    assert rows[2][1][0]["type"] == "tool_result" and rows[2][1][0]["is_error"] is False


async def test_c1_slow_action_gets_a_spoken_done(brain: Brain, laptop: FakeDevice) -> None:
    assert brain.groq is not None
    brain.groq.queue(
        Turn(text=["Opening it."], tool_calls=[{"name": "app_open", "arguments": {"app": "vlc"}}])
    )
    laptop.tools["app_open"] = {"ok": True, "output": {"opened": "VLC"}}
    laptop.before_result = lambda: brain.clock.sleep(2)
    sid, _ = await laptop.say("open vlc")
    first = await laptop.next("reply.delta")  # before simulated time moves: no heard cue
    assert first["text"] == "Opening it."
    said = spoken(await drive(brain.clock, laptop.reply(sid), step=0.05))
    assert said[0] in {"Done.", "All set.", "There you go.", "Easy."}
    with pytest.raises(TimeoutError):
        await laptop.next("reply.cue", within=0.2)


async def test_c1_failed_action_is_explained_with_a_next_step(
    brain: Brain, laptop: FakeDevice
) -> None:
    assert brain.groq is not None
    brain.groq.queue(
        Turn(
            text=["Opening Spotify."],
            tool_calls=[{"name": "app_open", "arguments": {"app": "spotify"}}],
        ),
        Turn(text=["Spotify isn't installed. Want the web player instead?"]),
    )
    laptop.tools["app_open"] = {
        "ok": False,
        "error": {"code": "not_installed", "message": "Spotify isn't installed."},
    }
    sid, _ = await laptop.say("open spotify")
    deltas = await laptop.reply(sid)
    assert spoken(deltas) == [
        "Opening Spotify.",
        "Spotify isn't installed.",
        "Want the web player instead?",
    ]
    followup = brain.groq.requests[1]
    assert "tools" not in followup  # the explanation turn can't call tools again
    assert followup["messages"][-1] == {
        "role": "tool",
        "tool_call_id": "call_0",
        "content": "ERROR: Spotify isn't installed.",
    }


async def test_a1_tier0_result_is_recorded_without_an_llm(brain: Brain, laptop: FakeDevice) -> None:
    assert brain.groq is not None
    ack = await laptop.call(
        "signal.handled_locally",
        {
            "signal_id": "s-a1",
            "text": "volume to 30",
            "intent": "volume_set",
            "slots": {"level": 30},
            "result": {"ok": True, "said": None},
        },
    )
    assert ack == {"ok": True, "data": {"signal_id": "s-a1", "tier": 0}}
    rows = await thread(brain, 3)
    assert [(r, t) for r, _, t in rows] == [("user", 0), ("assistant", 0), ("user", 0)]
    assert rows[1][1] == [
        {"type": "tool_use", "id": "local_s-a1", "name": "volume_set", "input": {"level": 30}}
    ]
    assert not brain.groq.requests


async def test_a3_tier0_failure_escalates_to_the_reflex(brain: Brain, laptop: FakeDevice) -> None:
    assert brain.groq is not None
    brain.groq.queue(Turn(text=["Spotify isn't on this laptop. Want the web player?"]))
    ack = await laptop.call(
        "signal.handled_locally",
        {
            "signal_id": "s-a3",
            "text": "open spotify",
            "intent": "app_open",
            "slots": {"app": "spotify"},
            "result": {
                "ok": False,
                "error": {"code": "not_installed", "message": "No app named spotify."},
            },
        },
    )
    assert ack["data"] == {"signal_id": "s-a3", "tier": 2}
    assert spoken(await laptop.reply("s-a3")) == [
        "Spotify isn't on this laptop.",
        "Want the web player?",
    ]
    msgs = brain.groq.requests[0]["messages"]
    assert msgs[-2]["tool_calls"][0]["function"]["name"] == "app_open"
    assert msgs[-1]["content"] == "ERROR: No app named spotify."


async def test_s1_stalled_stream_bridges_then_next_provider_answers(
    brain: Brain, laptop: FakeDevice
) -> None:
    assert brain.groq is not None and brain.mistral is not None
    brain.groq.queue(Turn(text=["Sure, ", "so the"], gap_s=5))
    brain.mistral.queue(Turn(text=["Here's the whole answer."]))
    sid, _ = await laptop.say("explain tides")
    deltas = await drive(brain.clock, laptop.reply(sid), step=0.05)
    assert spoken(deltas) == ["Here's the whole answer."]
    assert (await laptop.next("reply.cue"))["kind"] == "heard"
    [inc] = await incidents(brain)
    assert (inc.stage, inc.error, inc.remedy, inc.outcome) == (
        "llm",
        "stalled",
        "bridge",
        "recovered",
    )


async def test_every_provider_down_is_explained_never_silent(
    brain: Brain, laptop: FakeDevice
) -> None:
    assert brain.groq is not None and brain.mistral is not None
    brain.groq.queue(Turn(status=503))
    brain.mistral.queue(Turn(status=429, retry_after_s=60))
    sid, _ = await laptop.say("tell me a joke")
    deltas = await laptop.reply(sid)
    assert deltas[0]["tone"] == "serious" and "right now" in deltas[0]["text"]
    assert (await laptop.next("reply.cue"))["kind"] == "error"
    [inc] = await incidents(brain)
    assert (inc.stage, inc.outcome) == ("llm", "failed_explained")


async def test_s8_signal_past_its_deadline_is_explained(
    brain: Brain, laptop: FakeDevice, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert brain.groq is not None
    monkeypatch.setitem(ROLES, "reflex", RoleConfig(None, 1000, 1000, 300))  # never times out
    brain.groq.queue(Turn(text=["never"], ttft_s=500))
    sid, _ = await laptop.say("what's up")
    deltas = await drive(brain.clock, laptop.reply(sid), step=0.5, limit_s=120)
    assert spoken(deltas)[0] in {
        "That one got stuck on my side. Mind saying it again?",
        "I lost track of that one, sorry. Try me again?",
    }
    assert brain.clock.monotonic() >= 20
    kinds = {(await laptop.next("reply.cue"))["kind"], (await laptop.next("reply.cue"))["kind"]}
    assert kinds == {"heard", "error"}  # heard at 0.5 s (bridge), error with the explanation
    [inc] = await incidents(brain)
    assert (inc.stage, inc.remedy, inc.outcome) == ("deadline", "explain", "failed_explained")
    assert not brain.voice.sup.watches


async def test_ps1_banned_phrases_are_rewritten_before_speaking(
    brain: Brain, laptop: FakeDevice
) -> None:
    assert brain.groq is not None
    brain.groq.queue(
        Turn(text=["Certainly! I'd be happy to help with that. ", "Task completed successfully."])
    )
    sid, _ = await laptop.say("did it work")
    said = " ".join(spoken(await laptop.reply(sid)))
    assert said == "Done."
    for banned in ("Certainly", "happy to help", "completed successfully"):
        assert banned not in said
    # the live eval caught a model cheering with an emoji and *italics*: TTS would read them out
    brain.groq.queue(Turn(text=["Congrats! \U0001f389 You *earned* it. ✨"]))
    sid, _ = await laptop.say("I got the job")
    assert " ".join(spoken(await laptop.reply(sid))) == "Congrats! You earned it."


async def test_ps4_tone_tags_travel_as_tone_not_speech(brain: Brain, laptop: FakeDevice) -> None:
    assert brain.groq is not None
    brain.groq.queue(
        Turn(text=["[serious] Heads up, that costs money. ", "[cheerful] Want me to go ahead?"])
    )
    sid, _ = await laptop.say("buy it")
    deltas = [d for d in await laptop.reply(sid) if d["speak"]]
    assert [(d["tone"], d["text"]) for d in deltas] == [
        ("serious", "Heads up, that costs money."),
        ("cheerful", "Want me to go ahead?"),
    ]


async def test_lg1_switch_to_hindi_is_tier1_and_changes_nothing(
    brain: Brain, laptop: FakeDevice
) -> None:
    assert brain.groq is not None
    sid, ack = await laptop.say("Switch to Hindi")
    assert ack["data"]["tier"] == 1
    assert spoken(await laptop.reply(sid)) == [
        "Hindi's not ready yet, it's on the way. Sticking with English for now."
    ]
    assert not brain.groq.requests
    r = await brain.client.get(
        "/v2/settings", headers=brain.auth({"access_token": laptop.access_token})
    )
    assert r.json()["data"]["language"] == "en"


async def test_interrupt_stops_the_turn(brain: Brain, laptop: FakeDevice) -> None:
    assert brain.groq is not None
    brain.groq.queue(Turn(text=["One thing first. ", "Then another. ", "And more."], gap_s=1))
    sid, _ = await laptop.say("tell me everything")
    first = await drive(brain.clock, laptop.next("reply.delta"), step=0.05)
    assert first["text"] == "One thing first."
    ack = await laptop.call("signal.interrupt", {"signal_id": sid})
    assert ack["data"] == {"cancelled": sid}
    with pytest.raises(TimeoutError):
        await drive(brain.clock, laptop.next("reply.delta", within=0.3), step=0.1)
    assert not brain.voice.sup.watches


async def test_stop_by_voice_cancels_the_running_turn(brain: Brain, laptop: FakeDevice) -> None:
    assert brain.groq is not None
    brain.groq.queue(Turn(text=["Long ", "story"], ttft_s=30))
    sid, _ = await laptop.say("tell me a long story")
    stop_id, ack = await laptop.say("never mind")
    assert ack["data"]["tier"] == 1
    assert spoken(await laptop.reply(stop_id))[0] in {
        "On it.",
        "Got it.",
        "Sure thing.",
        "Yep.",
        "You got it.",
    }
    assert sid not in {w.signal_id for w in brain.voice.sup.watches.values()}


async def test_duplicate_signal_is_handled_once(brain: Brain, laptop: FakeDevice) -> None:
    assert brain.groq is not None
    brain.groq.queue(Turn(text=["Hi."]))
    sid, _ = await laptop.say("hey")
    _, again = await laptop.say("hey", signal_id=sid)
    assert again["data"] == {"signal_id": sid, "duplicate": True}
    await laptop.reply(sid)
    assert len(brain.groq.requests) == 1


async def test_partial_prefetch_is_used_by_the_final(brain: Brain, laptop: FakeDevice) -> None:
    assert brain.groq is not None
    brain.groq.queue(Turn(text=["Sure."]))
    ack = await laptop.call("signal.partial", {"signal_id": "s-pre", "text": "what's the"})
    assert ack["ok"] is True
    assert "s-pre" in {k[1] for k in brain.voice.prefetch}
    await laptop.say("what's the time", signal_id="s-pre")
    await laptop.reply("s-pre")
    assert not brain.voice.prefetch


async def test_device_trace_and_engine_incidents_are_accepted(
    brain: Brain, laptop: FakeDevice
) -> None:
    ack = await laptop.call(
        "signal.trace",
        {"signal_id": "s1", "spans": {"endpoint": 210, "first_audio": 860}, "tts_engine": "kokoro"},
    )
    assert ack["ok"] is True
    ack = await laptop.call(
        "engine.incident",
        {"role": "tts", "engine": "edge-tts", "error": "503", "remedy": "switch"},
    )
    assert ack["ok"] is True
    r = await brain.client.get(
        "/v2/incidents", headers=brain.auth({"access_token": laptop.access_token})
    )
    [item] = r.json()["data"]["items"]
    assert (item["stage"], item["engine_or_provider"], item["remedy"]) == (
        "tts",
        "edge-tts",
        "switch",
    )


async def test_tool_result_for_someone_elses_call_is_ignored(
    brain: Brain, laptop: FakeDevice
) -> None:
    assert brain.groq is not None
    brain.groq.queue(
        Turn(
            text=["Turning it up."],
            tool_calls=[{"name": "volume_change", "arguments": {"direction": "up"}}],
        )
    )
    other = FakeDevice(brain.url, await brain.sign_in("ben@example.com", "Ben"))
    await other.connect()
    try:
        sid, _ = await laptop.say("louder")
        call = await laptop.next("tool.call")
        ack = await other.call("tool.result", {"call_id": call["call_id"], "ok": True})
        assert ack["data"] == {"accepted": False}
        ack = await laptop.call("tool.result", {"call_id": call["call_id"], "ok": True})
        assert ack["data"] == {"accepted": True}
        await laptop.reply(sid)
    finally:
        await other.close()


async def test_reflex_only_offers_tools_the_device_can_run(brain: Brain) -> None:
    assert brain.groq is not None
    d = FakeDevice(brain.url, await brain.sign_in("asha@example.com", "Desktop PC"))
    await d.connect()
    try:
        await d.hello(capabilities=["volume", "media"])  # no brightness control, no app index
        brain.groq.queue(Turn(text=["Sure."]))
        sid, _ = await d.say("make the screen brighter")
        await d.reply(sid)
    finally:
        await d.close()
    offered = {t["function"]["name"] for t in brain.groq.requests[0]["tools"]}
    assert offered == {
        "volume_set",
        "volume_change",
        "volume_mute",
        "media_control",
        "media_play",
        "delegate",
    }
