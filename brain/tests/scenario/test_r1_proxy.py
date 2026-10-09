"""Voice proxy (API.md §2.5) and device engine plans (§18.3). Platform keys stay in the brain.
# proves §18, ENVIRONMENT §3.3"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from tests.conftest import Brain
from tests.fakes.device import FakeDevice

pytestmark = pytest.mark.scenario

WAV = b"RIFF\x24\x00\x00\x00WAVEfmt fake-orpheus-audio"


class FakeGroqAudio:
    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.statuses: list[int] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        status = self.statuses.pop(0) if self.statuses else 200
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "nope"}})
        if request.url.path.endswith("/audio/speech"):
            return httpx.Response(200, headers={"content-type": "audio/wav"}, content=WAV)
        assert request.url.path.endswith("/audio/transcriptions")
        return httpx.Response(200, json={"text": "  what time is it  "})


@pytest.fixture
def audio(brain: Brain) -> FakeGroqAudio:
    fake = FakeGroqAudio()
    chat = brain.fake_http.hosts["api.groq.com"]

    def groq(request: httpx.Request) -> Any:
        return fake.handle(request) if "/audio/" in request.url.path else chat(request)

    brain.fake_http.hosts["api.groq.com"] = groq
    return fake


async def test_tts_proxy_streams_orpheus_audio_with_the_tone_direction(
    brain: Brain, audio: FakeGroqAudio
) -> None:
    tokens = await brain.sign_in()
    r = await brain.client.post(
        "/v2/proxy/tts",
        json={"text": "Heads up, that costs money.", "tone": "serious"},
        headers=brain.auth(tokens),
    )
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    assert r.content == WAV
    [call] = audio.calls
    assert call.headers["authorization"] == "Bearer gk-test"
    sent = json.loads(call.content)
    assert sent["input"] == "[serious] Heads up, that costs money."
    assert sent["model"] == "canopylabs/orpheus-v1-english" and sent["voice"] == "daniel"


async def test_tts_proxy_quota_gone_is_explained_and_cools_down(
    brain: Brain, audio: FakeGroqAudio
) -> None:
    tokens = await brain.sign_in()
    audio.statuses = [429]
    r = await brain.client.post("/v2/proxy/tts", json={"text": "Hi."}, headers=brain.auth(tokens))
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "provider_unavailable"
    assert "this device's own voice" in r.json()["error"]["message"]
    r = await brain.client.post("/v2/proxy/tts", json={"text": "Hi."}, headers=brain.auth(tokens))
    assert r.status_code == 503 and len(audio.calls) == 1  # circuit open: Groq not called again


async def test_tts_proxy_takes_one_sentence(brain: Brain, audio: FakeGroqAudio) -> None:
    tokens = await brain.sign_in()
    r = await brain.client.post(
        "/v2/proxy/tts", json={"text": "x" * 201}, headers=brain.auth(tokens)
    )
    assert r.status_code == 422 and not audio.calls


async def test_stt_proxy_transcribes_raw_audio(brain: Brain, audio: FakeGroqAudio) -> None:
    tokens = await brain.sign_in()
    r = await brain.client.post(
        "/v2/proxy/stt?lang=en",
        content=WAV,
        headers=brain.auth(tokens) | {"content-type": "audio/wav"},
    )
    assert r.status_code == 200
    assert r.json()["data"] == {"text": "what time is it", "lang": "en"}
    [call] = audio.calls
    assert b"whisper-large-v3-turbo" in call.content and WAV in call.content


async def test_stt_proxy_rejects_non_audio_and_empty(brain: Brain, audio: FakeGroqAudio) -> None:
    tokens = await brain.sign_in()
    r = await brain.client.post("/v2/proxy/stt", json={"text": "hi"}, headers=brain.auth(tokens))
    assert r.status_code == 422
    r = await brain.client.post(
        "/v2/proxy/stt", content=b"", headers=brain.auth(tokens) | {"content-type": "audio/wav"}
    )
    assert r.status_code == 422 and not audio.calls


async def test_device_engine_plan_is_stored_on_the_device(brain: Brain) -> None:
    tokens = await brain.sign_in()
    d = FakeDevice(brain.url, tokens)
    await d.connect()
    try:
        plan = {
            "stt": [],
            "tts": ["edge-tts"],
            "local_llm": [],
            "scores": {"edge-tts": {"p95_ms": 420}},
            "degraded": True,
        }
        ack = await d.call("device.engine_plan", plan)
        assert ack == {"ok": True, "data": {"stored": True}}
    finally:
        await d.close()
    r = await brain.client.get("/v2/devices", headers=brain.auth(tokens))
    assert r.json()["data"]["items"][0]["engine_plan"] == plan
