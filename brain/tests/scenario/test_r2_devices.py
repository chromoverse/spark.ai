"""Cross-device control with FakeDevices (TESTING.md §4.1 E1 to E4, F1, G1, G2; §4.2 W1 to W3;
§4.5 S3). The phone is a mobile body; real ADB lands in R4. # proves §26, §19.2 re-route"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.db.models import Device, QueuedAction
from tests.conftest import Brain
from tests.fakes.clock import drive, until
from tests.fakes.device import FakeDevice
from tests.fakes.llm import Turn

pytestmark = pytest.mark.scenario

DESKTOP = ["apps", "volume", "media", "brightness", "files", "shell", "system"]
PHONE = ["apps", "media", "volume", "sms"]
ACKS = {"On it.", "Got it.", "Sure thing.", "Yep.", "You got it."}


def tool(name: str, **arguments: Any) -> dict[str, Any]:
    return {"name": name, "arguments": arguments}


def spoken(deltas: list[dict[str, Any]]) -> list[str]:
    return [d["text"] for d in deltas if d["speak"]]


async def device(
    brain: Brain, name: str, kind: str, caps: list[str], connect: bool = True
) -> FakeDevice:
    d = FakeDevice(brain.url, await brain.sign_in("asha@example.com", name, kind))
    if connect:
        await d.connect()
        await d.hello(capabilities=caps)
    return d


@pytest.fixture
async def laptop(brain: Brain) -> AsyncIterator[FakeDevice]:
    d = await device(brain, "Laptop", "desktop", DESKTOP)
    yield d
    await d.close()


@pytest.fixture
async def phone(brain: Brain) -> AsyncIterator[FakeDevice]:
    d = await device(brain, "Pixel", "mobile", PHONE)
    yield d
    await d.close()


def tool_calls(dev: FakeDevice, name: str) -> list[dict[str, Any]]:
    return [d for e, d in dev.inbox if e == "tool.call" and d["tool"] == name]


async def test_e1_open_youtube_on_my_phone(
    brain: Brain, laptop: FakeDevice, phone: FakeDevice
) -> None:
    """Target = the phone; the laptop speaks the ack before the phone's tool result."""
    assert brain.groq is not None
    brain.groq.queue(
        Turn(
            text=["Playing lo-fi on YouTube on your phone."],
            tool_calls=[tool("media_play", app="youtube", query="lo-fi", device="phone")],
        )
    )
    phone.tools["media_play"] = {"ok": True, "output": {"searching": "lo-fi", "in": "YouTube"}}
    gate = asyncio.Event()
    phone.before_result = gate.wait
    sid, _ = await laptop.say("open youtube on my phone and play lo-fi")
    call = await phone.next("tool.call")
    assert (call["tool"], call["input"]) == ("media_play", {"app": "youtube", "query": "lo-fi"})
    ack = await laptop.next("reply.delta")
    assert ack["text"] == "Playing lo-fi on YouTube on your phone."  # before the result
    gate.set()
    await laptop.reply(sid)
    assert (await laptop.next("reply.cue"))["kind"] == "done"
    assert tool_calls(laptop, "media_play") == []
    req = brain.groq.requests[0]
    play = next(t for t in req["tools"] if t["function"]["name"] == "media_play")
    assert "device" in play["function"]["parameters"]["properties"]
    assert "devices: Laptop (this one), Pixel (phone)" in req["messages"][-1]["content"]


async def _queue_for_offline_phone(brain: Brain, laptop: FakeDevice) -> FakeDevice:
    assert brain.groq is not None
    phone = await device(brain, "Pixel", "mobile", PHONE)  # known capabilities…
    await phone.close()  # …then offline
    brain.groq.queue(
        Turn(tool_calls=[tool("media_play", app="youtube", query="lo-fi", device="phone")]),
        Turn(text=["Your phone's offline. Want me to play it when it's back?"]),
    )
    sid, _ = await laptop.say("play lo-fi on youtube on my phone")
    assert spoken(await laptop.reply(sid)) == [
        "Your phone's offline.",
        "Want me to play it when it's back?",
    ]
    told = brain.groq.requests[1]["messages"][-1]["content"]
    assert told.startswith(
        "ERROR: Pixel is offline. Ask if they want it done when it's back online"
    )
    sid, ack = await laptop.say("yes please")
    assert ack["data"]["tier"] == 1
    assert spoken(await laptop.reply(sid)) == ["Okay, I'll do it when your Pixel is back online."]
    return phone


async def test_e2_offline_phone_gets_the_queued_run_when_it_is_back(
    brain: Brain, laptop: FakeDevice
) -> None:
    phone = await _queue_for_offline_phone(brain, laptop)
    back = FakeDevice(brain.url, {"access_token": phone.access_token, "device_id": phone.device_id})
    back.tools["media_play"] = {"ok": True, "output": {"in": "YouTube"}}
    phone = back
    try:
        await phone.connect()
        await phone.hello(capabilities=PHONE)
        call = await phone.next("tool.call")
        assert call["input"] == {"app": "youtube", "query": "lo-fi"}
        notice = await laptop.next("notice")
        assert (notice["text"], notice["from_device"]) == ("Done on Pixel.", phone.device_id)
        async with brain.rt.db() as db:
            [row] = (await db.scalars(select(QueuedAction))).all()
        assert row.fired_at is not None
    finally:
        await phone.close()


async def test_e2_queued_run_expires_after_an_hour(brain: Brain, laptop: FakeDevice) -> None:
    phone = await _queue_for_offline_phone(brain, laptop)
    brain.clock.advance(3601)
    r = await brain.client.post("/v2/auth/refresh", json={"refresh_token": phone.refresh_token})
    late = FakeDevice(brain.url, r.json()["data"])
    late.tools["media_play"] = {"ok": True, "output": {}}
    try:
        await late.connect()
        await late.hello(capabilities=PHONE)
        with pytest.raises(TimeoutError):
            await late.next("tool.call", within=0.5)
    finally:
        await late.close()


async def test_e3_two_phones_ask_once_then_remember(
    brain: Brain, laptop: FakeDevice, phone: FakeDevice
) -> None:
    assert brain.groq is not None
    galaxy = await device(brain, "Galaxy", "mobile", PHONE)
    try:
        phone.tools["media_play"] = {"ok": True, "output": {}}
        galaxy.tools["media_play"] = {"ok": True, "output": {}}
        brain.groq.queue(
            Turn(tool_calls=[tool("media_play", query="lo-fi", device="phone")]),
            Turn(text=["Which phone, the Galaxy or the Pixel?"]),
            Turn(
                text=["Playing it on the Pixel."],
                tool_calls=[tool("media_play", query="lo-fi", device="Pixel")],
            ),
            Turn(
                text=["On your phone."],
                tool_calls=[tool("media_play", query="jazz", device="phone")],
            ),
        )
        sid, _ = await laptop.say("play lo-fi on my phone")
        assert spoken(await laptop.reply(sid)) == ["Which phone, the Galaxy or the Pixel?"]
        assert "Galaxy and Pixel" in brain.groq.requests[1]["messages"][-1]["content"]
        sid, _ = await laptop.say("the pixel")
        await laptop.reply(sid)
        assert len(tool_calls(phone, "media_play")) == 1
        sid, _ = await laptop.say("play jazz on my phone")
        await laptop.reply(sid)
        assert [c["input"]["query"] for c in tool_calls(phone, "media_play")] == ["lo-fi", "jazz"]
        assert tool_calls(galaxy, "media_play") == []
        async with brain.rt.db() as db:
            pixel = await db.get_one(Device, __import__("uuid").UUID(phone.device_id))
        assert pixel.is_default_for == ["phone"]
    finally:
        await galaxy.close()


async def test_e4_capability_fallback_sends_the_sms_from_the_phone(
    brain: Brain, laptop: FakeDevice, phone: FakeDevice
) -> None:
    assert brain.groq is not None
    brain.groq.queue(
        Turn(
            text=["On it."],
            tool_calls=[tool("delegate", task="Text Mom that I'm on my way", ack="On it.")],
        )
    )
    brain.groq.queue(
        Turn(tool_calls=[tool("sms_send", to="Mom", text="On my way!")]),
        Turn(text=["Sent Mom your text from your phone."]),
        model="agent",
    )
    phone.tools["sms_send"] = {"ok": True, "output": {"sent": True}}
    sid, _ = await laptop.say("text mom that I'm on my way")
    await laptop.reply(sid)
    assert spoken(await laptop.reply(sid)) == ["Sending it from your phone."]  # the announcement
    req = await laptop.next("approval.request")
    assert (req["tool"], req["risk"]) == ("sms_send", "external")
    await laptop.reply(sid)  # "Heads up, this will text Mom: …"
    await laptop.call("approval.response", {"approval_id": req["approval_id"], "decision": "allow"})
    while (await laptop.next("job.update"))["status"] != "done":
        pass
    [call] = tool_calls(phone, "sms_send")
    assert call["input"] == {"to": "Mom", "text": "On my way!"}
    agent_tools = {t["function"]["name"] for t in brain.groq.for_model("agent")[0]["tools"]}
    assert "sms_send" in agent_tools  # offered because a device of the user can send texts


async def test_f1_pause_music_on_my_laptop_from_the_phone(
    brain: Brain, laptop: FakeDevice, phone: FakeDevice
) -> None:
    assert brain.groq is not None
    laptop.tools["media_control"] = {"ok": True, "output": {"action": "pause"}}
    sid, ack = await phone.say("pause the music on my laptop")
    assert ack["data"]["tier"] == 1
    call = await laptop.next("tool.call")
    assert (call["tool"], call["input"]) == ("media_control", {"action": "pause"})
    assert spoken(await phone.reply(sid)) == ["Paused on your laptop."]
    assert not brain.groq.requests  # no LLM


async def test_f1_not_sure_goes_to_the_reflex(brain: Brain, phone: FakeDevice) -> None:
    """No laptop registered: tier 1 can't be sure, so the reflex answers."""
    assert brain.groq is not None
    brain.groq.queue(Turn(text=["I don't see a laptop on your account yet."]))
    sid, ack = await phone.say("pause the music on my laptop")
    assert ack["data"]["tier"] == 2
    await phone.reply(sid)


async def test_g1_send_this_to_my_phone_with_a_signed_link(
    brain: Brain, laptop: FakeDevice, phone: FakeDevice
) -> None:
    auth = brain.auth({"access_token": laptop.access_token})
    r = await brain.client.post(
        "/v2/uploads?name=notes.txt&kind=text",
        content=b"buy milk",
        headers=auth | {"content-type": "text/plain"},
    )
    assert r.status_code == 200, r.text
    art = r.json()["data"]
    sid, ack = await laptop.say("send this to my phone")
    assert ack["data"]["tier"] == 1
    assert spoken(await laptop.reply(sid)) == ["Sent it to your Pixel."]
    notice = await phone.next("notice")
    assert (notice["artifact_id"], notice["text"]) == (art["id"], "From Laptop: notes.txt")
    url = notice["url"].replace(brain.rt.settings.public_url, brain.url)
    async with httpx.AsyncClient() as plain:  # no token: the signature is the permission
        got = await plain.get(url)
        assert (got.status_code, got.content) == (200, b"buy milk")
        bad = await plain.get(url[:-4] + "0000")
        assert bad.status_code == 404
        brain.clock.advance(3601)
        expired = await plain.get(url)
        assert expired.status_code == 404
    ben = brain.auth(await brain.sign_in("ben@example.com", "Ben"))
    assert (await brain.client.get(f"/v2/artifacts/{art['id']}", headers=ben)).status_code == 404


async def test_g2_continue_on_my_phone_shares_the_thread(
    brain: Brain, laptop: FakeDevice, phone: FakeDevice
) -> None:
    assert brain.groq is not None
    brain.groq.queue(Turn(text=["Kathmandu."]), Turn(text=["About a million people."]))
    sid, _ = await laptop.say("what's the capital of nepal")
    await laptop.reply(sid)
    brain.clock.advance(1)  # turns stored at one fake instant would tie on created_at
    sid, ack = await laptop.say("continue on my phone")
    assert ack["data"]["tier"] == 1
    assert spoken(await laptop.reply(sid)) == ["It's on your phone. Pick it up there."]
    notice = await phone.next("notice")
    thread_id = notice["thread_id"]
    as_phone = brain.auth({"access_token": phone.access_token})
    items = (await brain.client.get(f"/v2/threads/{thread_id}/messages", headers=as_phone)).json()[
        "data"
    ]["items"]
    texts = [b["text"] for m in items for b in m["content"] if b["type"] == "text"]
    assert texts[:2] == ["what's the capital of nepal", "Kathmandu."]
    brain.clock.advance(1)
    sid, _ = await phone.say("how many people live there")
    assert spoken(await phone.reply(sid)) == ["About a million people."]
    assert brain.groq.requests[1]["messages"][2]["content"] == "Kathmandu."  # the laptop's turn


async def _claim(
    dev: FakeDevice, score: float, loudness: float, foreground: bool = False
) -> dict[str, Any]:
    ack = await dev.call(
        "wake.claim", {"score": score, "loudness": loudness, "foreground": foreground}
    )
    data: dict[str, Any] = ack["data"]
    return data


async def test_w1_two_claims_one_grant(brain: Brain, laptop: FakeDevice, phone: FakeDevice) -> None:
    a = await _claim(laptop, 0.9, 0.6)
    b = await _claim(phone, 0.7, 0.3)
    assert a["decision"] == b["decision"] == "pending"
    grant = await drive(brain.clock, laptop.next("wake.grant"), step=0.05)
    yielded = await phone.next("wake.yield")
    assert (grant["claim_id"], yielded["claim_id"], yielded["winner"]) == (
        a["claim_id"],
        b["claim_id"],
        laptop.device_id,
    )
    _, ack = await phone.say("what time is it", source="voice")
    assert ack["data"]["duplicate"] is True  # the yielded device's line is dropped


async def test_w1_alone_is_granted_at_once(brain: Brain, laptop: FakeDevice) -> None:
    assert (await _claim(laptop, 0.5, 0.5))["decision"] == "grant"


async def test_w2_ties_go_to_the_foreground_then_the_most_recent(
    brain: Brain, laptop: FakeDevice, phone: FakeDevice
) -> None:
    await _claim(laptop, 0.8, 0.5)
    b = await _claim(phone, 0.8, 0.5, foreground=True)
    assert (await drive(brain.clock, phone.next("wake.grant"), step=0.05))["claim_id"] == b[
        "claim_id"
    ]
    brain.clock.advance(5)
    assert brain.groq is not None
    brain.groq.queue(Turn(text=["Hi."]))
    sid, _ = await laptop.say("hello", source="text")  # the laptop is now the most recent
    await laptop.reply(sid)
    a = await _claim(laptop, 0.8, 0.5)
    await _claim(phone, 0.8, 0.5)
    assert (await drive(brain.clock, laptop.next("wake.grant"), step=0.05))["claim_id"] == a[
        "claim_id"
    ]


async def test_w3_a_late_claim_is_new_only_if_the_words_differ(
    brain: Brain, laptop: FakeDevice, phone: FakeDevice
) -> None:
    assert brain.groq is not None
    await _claim(laptop, 0.9, 0.9)
    await drive(brain.clock, laptop.next("wake.grant"), step=0.05)
    brain.groq.queue(Turn(text=["It's nine."]), Turn(text=["Sunny."]))
    sid, _ = await laptop.say("what time is it", source="voice")
    late = await _claim(phone, 0.5, 0.5)  # after the window: its own window, granted
    assert (await drive(brain.clock, phone.next("wake.grant"), step=0.05))["claim_id"] == late[
        "claim_id"
    ]
    _, same = await phone.say("What time is it?", source="voice")
    assert same["data"]["duplicate"] is True
    sid2, other = await phone.say("what's the weather", source="voice")
    assert other["data"]["tier"] == 2
    await phone.reply(sid2)
    await laptop.reply(sid)


async def test_s3_device_drops_mid_job_and_another_takes_over(
    brain: Brain, laptop: FakeDevice
) -> None:
    assert brain.groq is not None
    desk = await device(brain, "Desktop PC", "desktop", DESKTOP)
    try:
        brain.groq.queue(
            Turn(
                text=["On it."],
                tool_calls=[tool("delegate", task="List my Downloads", ack="On it.")],
            )
        )
        brain.groq.queue(
            Turn(tool_calls=[tool("file_list", path="Downloads")]),
            Turn(text=["Downloads is empty."]),
            model="agent",
        )
        laptop.tools["file_list"] = lambda inp: None  # it goes to sleep instead of answering
        desk.tools["file_list"] = {"ok": True, "output": {"path": "Downloads", "items": []}}
        sid, _ = await laptop.say("list my downloads")
        await laptop.reply(sid)
        await until(lambda: tool_calls(laptop, "file_list"))
        await laptop.close()
        [call] = [await desk.next("tool.call")]
        assert call["tool"] == "file_list"
        seen = []
        while not seen or seen[-1]["status"] not in ("done", "failed"):
            seen.append(await desk.next("job.update"))
        assert seen[-1]["status"] == "done"
        assert any(
            u.get("note") == "That device went offline, so I'm using Desktop PC." for u in seen
        )
    finally:
        await desk.close()


async def test_s3_no_other_device_means_an_explanation(brain: Brain, laptop: FakeDevice) -> None:
    assert brain.groq is not None
    other = await device(brain, "Pixel", "mobile", PHONE)  # online, but no files
    try:
        brain.groq.queue(
            Turn(
                text=["On it."],
                tool_calls=[tool("delegate", task="List my Downloads", ack="On it.")],
            )
        )
        brain.groq.queue(
            Turn(tool_calls=[tool("file_list", path="Downloads")]),
            Turn(text=["Your laptop went offline before I could list Downloads."]),
            model="agent",
        )
        laptop.tools["file_list"] = lambda inp: None
        sid, _ = await laptop.say("list my downloads")
        await laptop.reply(sid)
        await until(lambda: tool_calls(laptop, "file_list"))
        await laptop.close()
        seen = []
        while not seen or seen[-1]["status"] not in ("done", "failed"):
            seen.append(await other.next("job.update"))
        told = brain.groq.for_model("agent")[1]["messages"][-1]["content"]
        assert told == "ERROR: That device went offline before it finished."
    finally:
        await other.close()
