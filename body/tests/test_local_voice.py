"""On-device voice: model catalog and downloads, STT fitness, the low-spec budget, and the wake
word gate (TESTING.md §4.4 FT7 to FT10, §4.2 WK1 to WK3). # proves §18, §4.1"""

from __future__ import annotations

import base64
import hashlib
import io
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from spark_body import models
from spark_body.app import Body, data_dir
from spark_body.clock import Clock
from spark_body.ear.stt import LocalStt, Transcript
from spark_body.ear.wake import Wake, strip_wake
from spark_body.fitness import (
    ACCURACY_TEXT,
    PROBE_TEXT,
    Fitness,
    accuracy,
    accuracy_clip,
    budgets,
    probe_clip,
)
from spark_body.mouth.engines import LocalTts
from tests.fakes.clock import FakeClock, drive
from tests.fakes.engines import FakeTts
from tests.test_body import Wire

LAPTOP = {"cores": 8, "ram_gb": 7.4}  # the owner's Ryzen 7 4700U


@dataclass
class FakeStt:
    name: str
    clock: FakeClock
    latency_s: float = 0.1
    text: str | None = None  # None: hears every clip perfectly
    on_device: bool = True
    heard: list[int] = field(default_factory=list)

    def available(self) -> bool:
        return True

    async def transcribe(self, pcm16: bytes, sample_rate: int) -> Transcript:
        self.heard.append(len(pcm16))
        await self.clock.sleep(self.latency_s)
        if self.text is not None:
            return Transcript(self.text)
        return Transcript(ACCURACY_TEXT if pcm16 == accuracy_clip()[0] else PROBE_TEXT)


@dataclass
class FakeWake:
    cut: int | None  # where the command starts (sample index), None = no wake phrase
    calls: int = 0

    def available(self) -> bool:
        return True

    async def find(self, pcm16: bytes, sample_rate: int) -> int | None:
        self.calls += 1
        return self.cut


ONE_SECOND = base64.b64encode(b"\x00\x01" * 16000).decode()


def test_tier_picks_what_a_device_downloads() -> None:
    assert models.tier(LAPTOP) == 0
    low = {m.name for m in models.wanted(LAPTOP)}
    assert low == {"kws-gigaspeech", "piper", "moonshine-tiny"}
    big = {m.name for m in models.wanted({"cores": 16, "ram_gb": 32})}
    assert big == low | {"kokoro", "parakeet"}
    assert all(len(m.sha256) == 64 for m in models.CATALOG)


async def test_ft7_low_spec_budget_lets_the_expressive_cloud_voice_lead() -> None:
    async def plan(tier: int) -> list[str]:
        clock = FakeClock()
        es = {
            "groq-orpheus": FakeTts("groq-orpheus", clock, latency_s=0.65, expressive=True),
            "piper": FakeTts("piper", clock, latency_s=0.23),
        }
        fit = Fitness(es, clock, budget=budgets(tier))  # type: ignore[arg-type]
        return (await drive(clock, fit.full())).tts

    assert await plan(0) == ["groq-orpheus", "piper"]  # ≤ 2 s first audio target
    assert await plan(1) == ["piper", "groq-orpheus"]  # 1 s target: only piper fits


async def test_quick_check_refreshes_good_scores_and_spends_nothing_on_fallbacks() -> None:
    clock = FakeClock()
    es = {
        "piper": FakeTts("piper", clock, latency_s=0.15),
        "edge-tts": FakeTts("edge-tts", clock, latency_s=0.9),
    }
    fit = Fitness(es, clock)  # type: ignore[arg-type]
    await drive(clock, fit.full())
    assert fit.plan.tts == ["piper", "edge-tts"]  # edge is over budget: a fallback only
    edge_calls = len(es["edge-tts"].texts)
    await drive(clock, fit.quick())
    assert fit.plan.scores["piper"].ewma_ms is not None  # the fresh probe counts
    assert len(es["edge-tts"].texts) == edge_calls


async def test_ft8_stt_plan_ranks_accuracy_then_speed_and_keeps_slow_fallbacks() -> None:
    clock = FakeClock()
    ears = {
        "groq-whisper": FakeStt("groq-whisper", clock, latency_s=0.55, on_device=False),
        "sloppy": FakeStt("sloppy", clock, latency_s=0.05, text="hey mark turn the volume"),
        "moonshine-tiny": FakeStt("moonshine-tiny", clock, latency_s=0.12),
    }
    fit = Fitness({}, clock, ears=ears)  # type: ignore[arg-type]
    plan = await drive(clock, fit.full())
    assert plan.stt == ["moonshine-tiny", "sloppy", "groq-whisper"]
    assert plan.scores["moonshine-tiny"].accuracy == 1.0
    assert plan.scores["sloppy"].accuracy is not None and plan.scores["sloppy"].accuracy < 0.7
    assert plan.wire()["stt"] == plan.stt


def test_accuracy_is_one_minus_word_error_rate() -> None:
    assert (
        accuracy(
            "Hey Spark, turn the volume up to thirty.", "hey spark turn the volume up to thirty"
        )
        == 1.0
    )
    assert accuracy("turn the volume up", "turn volume up") == 0.75
    assert accuracy("hi", "") == 0.0


def test_strip_wake_handles_what_stt_makes_of_it() -> None:
    assert strip_wake("Hey Spark, what time is it?") == "what time is it?"
    assert strip_wake("I spark, turn the volume up to thirty.") == "turn the volume up to thirty."
    assert strip_wake("Okay, Spark, open Spotify") == "open Spotify"
    assert strip_wake("Hey, Spark.") == ""
    assert strip_wake("Sparks what's the weather") == "what's the weather"
    assert strip_wake("Turn it up") == "Turn it up"


def _archive(tmp: Path, members: dict[str, bytes]) -> tuple[str, str]:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:bz2") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    (tmp / "rel").mkdir(exist_ok=True)
    (tmp / "rel" / "m.tar.bz2").write_bytes(buf.getvalue())
    return "rel/m.tar.bz2", hashlib.sha256(buf.getvalue()).hexdigest()


def test_fetch_verifies_unpacks_and_is_idempotent(tmp_path: Path, monkeypatch: Any) -> None:
    asset, sha = _archive(
        tmp_path, {"voice-v1/model.onnx": b"weights", "voice-v1/tokens.txt": b"a"}
    )
    monkeypatch.setattr(models, "RELEASES", tmp_path.as_uri())
    m = models.Model("voice", "tts", "vits", asset, sha, 1, 0, "MIT")
    root = tmp_path / "models"
    seen: list[int] = []
    folder = models.fetch(m, root, lambda done, total: seen.append(done))
    assert folder == root / "voice" and (folder / "model.onnx").read_bytes() == b"weights"
    assert models.installed(root, "voice") == folder and seen
    assert models.one(folder, "*.onnx").endswith("model.onnx")
    (tmp_path / "rel" / "m.tar.bz2").unlink()  # a second call doesn't download again
    assert models.fetch(m, root) == folder
    assert sorted(p.name for p in root.iterdir()) == ["voice"]


def test_fetch_rejects_a_bad_checksum_and_unsafe_paths(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(models, "RELEASES", tmp_path.as_uri())
    root = tmp_path / "models"
    asset, _ = _archive(tmp_path, {"v/model.onnx": b"x"})
    with pytest.raises(ValueError, match="checksum"):
        models.fetch(models.Model("bad", "tts", "vits", asset, "0" * 64, 1, 0, "MIT"), root)
    assert list(root.iterdir()) == []
    asset, sha = _archive(tmp_path, {"../../evil.txt": b"x"})
    with pytest.raises(tarfile.TarError):
        models.fetch(models.Model("evil", "tts", "vits", asset, sha, 1, 0, "MIT"), root)
    assert models.installed(root, "evil") is None and not (tmp_path / "evil.txt").exists()


async def test_ft9_models_download_in_the_background_and_failures_are_reported(
    tmp_path: Path, monkeypatch: Any
) -> None:
    good, sha = _archive(tmp_path, {"g/model.onnx": b"w"})
    catalog = (
        models.Model("good", "stt", "moonshine", good, sha, 1, 0, "MIT"),
        models.Model("broken", "tts", "vits", good, "0" * 64, 1, 0, "MIT"),
    )
    monkeypatch.setattr(models, "CATALOG", catalog)
    monkeypatch.setattr(models, "RELEASES", tmp_path.as_uri())
    monkeypatch.setattr(models, "runtime", lambda: True)
    wire = Wire()
    body = Body(wire.rpc, {}, models_root=tmp_path / "models")
    assert await body.fetch_models(LAPTOP) is True
    assert body.downloads["good"]["state"] == "ready"
    assert body.downloads["broken"]["state"] == "failed"
    assert {"name": "good", "pct": 100} in wire.notes("models.progress")
    [inc] = wire.notes("watchdog.incident")
    assert (inc["role"], inc["engine"], inc["outcome"]) == ("tts", "broken", "degraded")
    plan = await wire.call("engine.plan", {})
    assert plan["result"]["models"]["good"]["pct"] == 100
    assert plan["result"]["budget_ms"] == {"tts": 250.0, "stt": 300.0}


async def test_wk1_without_the_wake_word_nothing_is_transcribed() -> None:
    wire = Wire()
    clock = FakeClock()
    ear = FakeStt("moonshine-tiny", clock, latency_s=0)
    body = Body(wire.rpc, {}, clock, ears={"moonshine-tiny": ear}, wake=FakeWake(None))  # type: ignore[dict-item,arg-type]
    pcm = base64.b64encode(b"\x00\x01" * 1600).decode()
    r = await wire.call("stt.transcribe", {"pcm16": pcm, "wake": True})
    assert r["result"] == {"text": "", "wake": False}
    assert len(ear.heard) == 1  # the on-device second-chance check; nothing else heard it
    # in a follow-up window the renderer doesn't ask for the wake word
    r = await wire.call("stt.transcribe", {"pcm16": pcm}, req_id=2)
    assert r["result"]["text"] == PROBE_TEXT and r["result"]["wake"] is None
    assert body.wake.calls == 1  # type: ignore[union-attr]


async def test_wk2_wake_word_and_command_in_one_breath() -> None:
    wire = Wire()
    clock = FakeClock()
    ear = FakeStt("moonshine-tiny", clock, latency_s=0, text="Spark, what time is it?")
    wake = FakeWake(6000)
    Body(wire.rpc, {}, clock, ears={"moonshine-tiny": ear}, wake=wake)  # type: ignore[dict-item,arg-type]
    r = await wire.call("stt.transcribe", {"pcm16": ONE_SECOND, "wake": True})
    assert r["result"]["text"] == "what time is it?" and r["result"]["wake"] is True
    assert ear.heard == [(16000 - 6000) * 2]  # STT hears only what follows the phrase
    wake.cut = 15000  # just "Hey Spark": the renderer opens a listening window
    r = await wire.call("stt.transcribe", {"pcm16": ONE_SECOND, "wake": True}, req_id=2)
    assert r["result"] == {"text": "", "wake": True} and len(ear.heard) == 1


async def test_wk4_second_chance_catches_what_the_spotter_missed() -> None:
    wire = Wire()
    clock = FakeClock()
    local = FakeStt("moonshine-tiny", clock, latency_s=0, text="Spark, what time is it?")
    cloud = FakeStt("groq-whisper", clock, latency_s=0, text="Spark, what time is it?")
    cloud.on_device = False
    body = Body(
        wire.rpc,
        {},
        clock,
        ears={"groq-whisper": cloud, "moonshine-tiny": local},  # type: ignore[dict-item]
        wake=FakeWake(None),  # type: ignore[arg-type]
    )
    r = await wire.call("stt.transcribe", {"pcm16": ONE_SECOND, "wake": True})
    assert r["result"]["text"] == "what time is it?" and r["result"]["wake"] is True
    assert r["result"]["engine"] == "groq-whisper"  # the plan's best ear hears the command
    assert len(local.heard) == 1  # the wake check stayed on the device
    local.text = "Hey, Spark."
    r = await wire.call("stt.transcribe", {"pcm16": ONE_SECOND, "wake": True}, req_id=2)
    assert r["result"] == {"text": "", "wake": True}
    local.text = "A spark of genius, that idea."  # not a wake phrase
    r = await wire.call("stt.transcribe", {"pcm16": ONE_SECOND, "wake": True}, req_id=3)
    assert r["result"] == {"text": "", "wake": False} and len(cloud.heard) == 1
    assert body.fitness.plan.budget["stt"] == 300  # default tier


def test_low_spec_budgets_favor_accuracy() -> None:
    assert budgets(0) == {"tts": 700.0, "stt": 700.0}
    assert budgets(2) == {"tts": 250.0, "stt": 300.0}


async def test_wk3_no_wake_model_yet_means_open_mic() -> None:
    wire = Wire()
    clock = FakeClock()
    ear = FakeStt("groq-whisper", clock, latency_s=0, text="what time is it")
    Body(wire.rpc, {}, clock, ears={"groq-whisper": ear}, wake=Wake(Path("nowhere")))  # type: ignore[dict-item]
    pcm = base64.b64encode(b"\x00\x01" * 1600).decode()
    r = await wire.call("stt.transcribe", {"pcm16": pcm, "wake": True})
    assert r["result"]["text"] == "what time is it" and r["result"]["wake"] is None


# Real models, when this machine has them (the body downloads them on first run). CI skips.
ROOT = data_dir() / "models"


def _have(*names: str) -> bool:
    return models.runtime() and all(models.installed(ROOT, n) for n in names)


def _say(text: str) -> tuple[bytes, int]:
    """Speech from the local voice, as the mic path hands it over (16-bit PCM)."""
    import asyncio
    import wave

    async def clip() -> bytes:
        return b"".join(
            [c async for c in LocalTts(models.BY_NAME["piper"], ROOT).synth(text, None)]
        )

    with wave.open(io.BytesIO(asyncio.run(clip())), "rb") as w:
        return w.readframes(w.getnframes()), w.getframerate()


@pytest.mark.skipif(
    not _have("kws-gigaspeech", "moonshine-tiny", "piper"), reason="models not downloaded"
)
def test_ft10_real_wake_word_cut_then_stt() -> None:
    import asyncio

    pcm, rate = _say("Hey Spark, turn the volume up to thirty.")
    wake = Wake(ROOT)
    cut = asyncio.run(wake.find(pcm, rate))
    assert cut is not None and 0.4 < cut / rate < 1.5, cut
    heard = asyncio.run(
        LocalStt(models.BY_NAME["moonshine-tiny"], ROOT).transcribe(pcm[cut * 2 :], rate)
    )
    # Piper varies each run and the cut is approximate: ~74% words right on average (2026-10-10)
    assert accuracy("turn the volume up to thirty", heard.text) >= 0.6, heard.text
    near_miss, _ = _say("The park was sparkling today.")
    assert asyncio.run(Wake(ROOT).find(near_miss, rate)) is None
    probe, probe_rate = probe_clip()  # the fitness clip: a plain command, no wake phrase
    heard = asyncio.run(
        LocalStt(models.BY_NAME["moonshine-tiny"], ROOT).transcribe(probe, probe_rate)
    )
    assert accuracy(PROBE_TEXT, heard.text) >= 0.8, heard.text


@pytest.mark.skipif(not _have("piper"), reason="models not downloaded")
async def test_ft10_real_local_voice_speaks_a_wav() -> None:
    tts = LocalTts(models.BY_NAME["piper"], ROOT)
    clips = [c async for c in tts.synth("Done.", None)]
    assert len(clips) == 1 and clips[0][:4] == b"RIFF" and len(clips[0]) > 10_000
    fit = Fitness({"piper": tts}, Clock())  # type: ignore[dict-item]
    plan = await fit.full("test")
    assert plan.scores["piper"].success == 1.0
