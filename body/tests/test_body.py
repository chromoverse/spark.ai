"""The sidecar end to end over JSON-RPC: tier 0 on the device (A1/A3 device half), stop, repeat,
tool.run, and the RPC framing. # proves §26.4-A, API.md §4"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from spark_body import hands
from spark_body.app import Body
from spark_body.ear.endpoint import Endpointer
from spark_body.hands import apps
from spark_body.rpc import Rpc
from tests.fakes.clock import FakeClock
from tests.fakes.engines import FakeTts


class Wire:
    """Electron main's side of the stdio pipe."""

    def __init__(self) -> None:
        self.out: list[dict[str, Any]] = []
        self.rpc = Rpc(write=lambda b: self.out.append(json.loads(b)))

    async def call(self, method: str, params: dict[str, Any], req_id: int = 1) -> dict[str, Any]:
        self.rpc.handle_line(
            json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        )
        for _ in range(200):
            await asyncio.sleep(0)
            for msg in self.out:
                if msg.get("id") == req_id:
                    self.out.remove(msg)
                    return msg
        raise AssertionError(f"no reply to {method}")

    def notes(self, method: str) -> list[dict[str, Any]]:
        return [m["params"] for m in self.out if m.get("method") == method]


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> Wire:
    ran: list[tuple[str, dict[str, Any]]] = []

    def fake_hand(name: str) -> Any:
        def hand(inp: dict[str, Any]) -> dict[str, Any]:
            ran.append((name, inp))
            if name == "app_open" and inp["app"] == "Broken":
                raise apps.NotInstalled("No app named 'Broken' is installed here.")
            return {"done": name}

        return hand

    monkeypatch.setattr(hands, "HANDS", {n: fake_hand(n) for n in hands.HANDS})
    monkeypatch.setattr(
        apps.INDEX, "entries", {"spotify": ("Spotify", "x.lnk"), "broken": ("Broken", "y.lnk")}
    )
    w = Wire()
    w.ran = ran  # type: ignore[attr-defined]
    return w


@pytest.fixture
async def body(wire: Wire) -> Body:
    clock = FakeClock()
    b = Body(wire.rpc, {"kokoro": FakeTts("kokoro", clock, latency_s=0)}, clock)  # type: ignore[dict-item]
    b.mouth.plan = ["kokoro"]
    return b


async def test_a1_device_half_volume_runs_locally_with_a_chime(wire: Wire, body: Body) -> None:
    r = await wire.call("reflex.handle", {"text": "Hey Spark, volume to 30"})
    assert r["result"] == {
        "handled": True,
        "intent": "volume_set",
        "slots": {"level": 30},
        "result": {"ok": True, "said": None, "output": {"done": "volume_set"}},
        "chime": True,
    }
    assert wire.ran == [("volume_set", {"level": 30})]  # type: ignore[attr-defined]


async def test_a3_device_half_failure_is_handed_to_the_brain(wire: Wire, body: Body) -> None:
    r = (await wire.call("reflex.handle", {"text": "open broken"}))["result"]
    assert r["handled"] is True and r["result"]["ok"] is False
    assert r["result"]["error"]["code"] == "not_installed"


async def test_open_app_speaks_a_short_ack(wire: Wire, body: Body) -> None:
    r = (await wire.call("reflex.handle", {"text": "open spotify"}))["result"]
    assert r["result"]["said"] in {
        "Opening Spotify.",
        "Spotify, coming up.",
        "Here's Spotify.",
        "On it.",
    }


async def test_not_sure_goes_to_the_brain(wire: Wire, body: Body) -> None:
    r = await wire.call("reflex.handle", {"text": "play a song that fits my mood"})
    assert r["result"] == {"handled": False}
    assert wire.ran == []  # type: ignore[attr-defined]


async def test_stop_and_repeat(wire: Wire, body: Body) -> None:
    r = (await wire.call("reflex.handle", {"text": "repeat that"}))["result"]
    assert r == {"handled": False}  # nothing said yet: the brain answers
    body.speak("u1", "It's two o'clock.")
    r = (await wire.call("reflex.handle", {"text": "say that again"}))["result"]
    assert r == {"handled": True, "intent": "repeat", "record": False}
    assert [u.text for u in list(body.mouth.queue._queue)][-1] == "It's two o'clock."  # type: ignore[attr-defined]
    r = (await wire.call("reflex.handle", {"text": "stop"}))["result"]
    assert r == {"handled": True, "intent": "stop", "interrupt": True}
    assert body.mouth.queue.empty()


async def test_tool_run_returns_output_or_actionable_error(wire: Wire, body: Body) -> None:
    ok = await wire.call("tool.run", {"tool": "media_control", "input": {"action": "next"}})
    assert ok["result"] == {"ok": True, "output": {"done": "media_control"}}
    bad = await wire.call("tool.run", {"tool": "app_open", "input": {"app": "Broken"}}, req_id=2)
    assert bad["result"]["ok"] is False and bad["result"]["error"]["code"] == "not_installed"
    unknown = await wire.call("tool.run", {"tool": "rm_rf", "input": {}}, req_id=3)
    assert unknown["result"]["error"]["code"] == "unknown_tool"


async def test_rpc_errors_are_json_rpc_shaped(wire: Wire, body: Body) -> None:
    r = await wire.call("nope", {})
    assert r["error"]["code"] == -32601
    r = await wire.call("tts.speak", {"utt_id": 5}, req_id=2)
    assert r["error"]["code"] == -32602
    wire.rpc.handle_line("{not json")
    assert wire.out[-1]["error"]["code"] == -32700


async def test_tts_speak_streams_audio_notifications(wire: Wire, body: Body) -> None:
    body.mouth.start()
    r = await wire.call("tts.speak", {"utt_id": "u9", "text": "Hello there.", "tone": None})
    assert r["result"] == {"queued": True}
    for _ in range(200):
        await asyncio.sleep(0)
        if wire.notes("mouth.done"):
            break
    assert wire.notes("mouth.done")[0]["ok"] is True
    assert len(wire.notes("mouth.audio")) == 2
    await body.mouth.close()


def test_endpointer_speculative_end_resume_and_echo_guard() -> None:
    ep = Endpointer()
    events: list[str] = []
    for p in [0.9] * 4 + [0.1] * 7:  # 128 ms speech, then 224 ms silence
        events += ep.feed(p)
    assert events == ["start", "end"]
    events = []
    for p in [0.9] * 4:  # speech resumes inside the window: cancel the speculative final
        events += ep.feed(p)
    assert events == ["resume"]
    for p in [0.1] * 40:
        events += ep.feed(p)
    assert events[-2:] == ["end", "closed"]

    ep = Endpointer(speaking=True)  # Spark is talking: its own echo (moderate prob) is ignored
    assert [e for p in [0.7] * 20 for e in ep.feed(p)] == []
    assert [e for p in [0.95] * 7 for e in ep.feed(p)] == ["barge_in"]


class FakeStt:
    def __init__(self, name: str, text: str | None) -> None:
        self.name, self.text, self.on_device = name, text, True
        self.heard: list[int] = []

    def available(self) -> bool:
        return True

    async def transcribe(self, pcm16: bytes, sample_rate: int) -> Any:
        from spark_body.ear.stt import Transcript

        self.heard.append(len(pcm16))
        if self.text is None:
            raise ConnectionError("engine down")
        return Transcript(self.text)


async def test_stt_switches_engines_and_reports_the_incident(wire: Wire, body: Body) -> None:
    import base64

    broken, good = FakeStt("local", None), FakeStt("groq-whisper", "what time is it")
    body.ears = {"local": broken, "groq-whisper": good}  # type: ignore[dict-item]
    pcm = base64.b64encode(b"\x00\x01" * 1600).decode()
    r = await wire.call("stt.transcribe", {"pcm16": pcm, "sample_rate": 16000})
    assert r["result"]["text"] == "what time is it" and r["result"]["engine"] == "groq-whisper"
    assert broken.heard == good.heard == [3200]
    [inc] = wire.notes("watchdog.incident")
    assert (inc["role"], inc["engine"], inc["remedy"]) == ("stt", "local", "switch")
    body.ears = {}
    r = await wire.call("stt.transcribe", {"pcm16": pcm}, req_id=2)
    assert r["error"]["code"] == -32000 and "Sign in" in r["error"]["message"]
