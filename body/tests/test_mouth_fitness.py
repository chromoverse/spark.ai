"""Device fitness and the mouth (TESTING.md §4.4 FT1 to FT6, barge-in). # proves §18, §19.2"""

from __future__ import annotations

import asyncio
import base64
from typing import Any

from spark_body.fitness import BUDGET_MS, Fitness, Score, select
from spark_body.mouth.engines import prepare
from spark_body.mouth.speaker import Mouth, Utterance
from tests.fakes.clock import FakeClock, drive
from tests.fakes.engines import FakeTts


class Notes:
    def __init__(self) -> None:
        self.items: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, method: str, params: dict[str, Any]) -> None:
        self.items.append((method, params))

    def of(self, method: str) -> list[dict[str, Any]]:
        return [p for m, p in self.items if m == method]


def engines(clock: FakeClock, **specs: dict[str, Any]) -> dict[str, FakeTts]:
    return {name: FakeTts(name, clock, **spec) for name, spec in specs.items()}


async def test_ft1_full_benchmark_drops_slow_and_orders_by_expressiveness() -> None:
    clock = FakeClock()
    es = engines(
        clock,
        kokoro={"latency_s": 0.15},
        orpheus={"latency_s": 0.2, "expressive": True},
        piper={"latency_s": 0.05},
        chatterbox={"latency_s": 0.9},  # over the 250 ms budget
        pocket={"latency_s": 0.05, "installed": False},  # extra not installed
    )
    fit = Fitness(es, clock)
    plan = await drive(clock, fit.full())
    assert plan.tts == ["orpheus", "piper", "kokoro", "chatterbox"]  # over budget: last resort
    assert plan.scores["chatterbox"].p95_ms is not None and plan.scores["chatterbox"].p95_ms > 250
    assert plan.scores["pocket"].success == 0
    wire = plan.wire()
    assert wire["tts"] == plan.tts and wire["stt"] == []
    assert {h["engine"] for h in fit.history()} == set(es)


async def test_ft2_quick_check_is_fast_and_keeps_a_stable_plan() -> None:
    clock = FakeClock()
    es = engines(clock, kokoro={"latency_s": 0.15}, piper={"latency_s": 0.05})
    changes: list[list[str]] = []
    fit = Fitness(es, clock, on_change=lambda p: changes.append(list(p.tts)))
    await drive(clock, fit.full())
    t0 = clock.monotonic()
    plan = await drive(clock, fit.quick())
    assert clock.monotonic() - t0 <= 2.0
    assert plan.tts == ["piper", "kokoro"] and changes == [["piper", "kokoro"]]


async def test_ft3_power_change_reprobes_and_updates_the_plan(tmp_path: Any) -> None:
    clock = FakeClock()
    es = engines(clock, kokoro={"latency_s": 0.1}, piper={"latency_s": 0.2})
    fit = Fitness(es, clock, db_path=tmp_path / "fitness.db")
    await drive(clock, fit.full())
    assert fit.plan.tts == ["kokoro", "piper"]
    es["kokoro"].latency_s = 0.6  # battery saver halves the CPU
    plan = await drive(clock, fit.power_changed())
    assert plan.tts == ["piper", "kokoro"]  # kokoro now over budget: fallback only
    # the plan survives a restart (quick check builds on it)
    again = Fitness(es, clock, db_path=tmp_path / "fitness.db")
    assert again.plan.tts == ["piper", "kokoro"]


async def test_ft11_throttled_cpu_demotes_the_local_engine_on_the_next_start(tmp_path: Any) -> None:
    """R1 acceptance: the CPU got slower between runs (thermal limit, a busy machine): the
    start-up quick check catches it and the plan changes before the first reply."""
    clock = FakeClock()
    es = engines(clock, piper={"latency_s": 0.1}, edge={"latency_s": 0.2})
    await drive(clock, Fitness(es, clock, db_path=tmp_path / "fitness.db").full())
    es["piper"].latency_s = 0.9  # the CPU-bound local voice, now 9x slower; the cloud one isn't
    changes: list[list[str]] = []
    restarted = Fitness(
        es, clock, db_path=tmp_path / "fitness.db", on_change=lambda p: changes.append(p.tts)
    )
    assert restarted.plan.tts == ["piper", "edge"]  # last run's plan, before the check
    plan = await drive(clock, restarted.quick())
    assert plan.tts == ["edge", "piper"] and changes == [["edge", "piper"]]
    assert not plan.scores["piper"].fits(plan.budget)  # kept only as a last-resort fallback


def test_nothing_fits_keeps_working_engines_fastest_first() -> None:
    scores = {
        "edge-tts": Score("edge-tts", "tts", 400, 520, 1.0, False),
        "slowpoke": Score("slowpoke", "tts", 800, 900, 1.0, False),
        "broken": Score("broken", "tts", None, None, 0.0, False),
    }
    assert select(scores) == ["edge-tts", "slowpoke"]


async def test_live_ewma_demotes_an_engine_that_slows_down() -> None:
    clock = FakeClock()
    es = engines(clock, kokoro={"latency_s": 0.1}, piper={"latency_s": 0.2})
    fit = Fitness(es, clock)
    await drive(clock, fit.full())
    for _ in range(10):
        fit.observe("kokoro", 600)
    assert fit.plan.tts == ["piper", "kokoro"]  # demoted to fallback


async def speak(mouth: Mouth, clock: FakeClock, text: str, tone: str | None = None) -> bool:
    return await drive(clock, mouth.say(Utterance("u1", text, tone)))


async def test_ft4_empty_audio_switches_for_the_same_sentence_then_demotes() -> None:
    clock = FakeClock()
    es = engines(clock, kokoro={}, piper={})
    es["kokoro"].script.extend(["empty", "empty"])
    notes = Notes()
    mouth = Mouth(es, ["kokoro", "piper"], notes, clock)  # type: ignore[arg-type]
    assert await speak(mouth, clock, "First one.")
    assert es["piper"].texts == ["First one."]  # same sentence, next engine
    [inc] = notes.of("watchdog.incident")
    assert inc | {"engine": "kokoro", "error": "empty audio", "remedy": "switch"} == inc
    assert await speak(mouth, clock, "Second one.")
    assert mouth.state["kokoro"].open_until > clock.monotonic()  # 2 strikes → out for 10 min
    assert await speak(mouth, clock, "Third one.")
    assert es["kokoro"].texts == ["First one.", "Second one."]
    assert "kokoro returned no audio → switched to piper for 10 min" in mouth.state["kokoro"].reason


async def test_ft5_tone_tags_kept_for_orpheus_stripped_elsewhere() -> None:
    clock = FakeClock()
    orpheus = FakeTts("orpheus", clock, expressive=True)
    kokoro = FakeTts("kokoro", clock)
    assert prepare(orpheus, "Heads up, that costs money.", "serious") == (
        "[serious] Heads up, that costs money."
    )
    assert prepare(kokoro, "[serious] Heads up, that costs money.", "serious") == (
        "Heads up, that costs money."
    )
    assert prepare(orpheus, "Hey.", "chill") == "Hey."  # chill is the default voice
    mouth = Mouth({"kokoro": kokoro}, ["kokoro"], Notes(), clock)  # type: ignore[dict-item]
    await speak(mouth, clock, "[cheerful] All set.", "cheerful")
    assert kokoro.texts == ["All set."]


async def test_ft6_edge_503_opens_circuit_for_10_min_with_a_reason() -> None:
    clock = FakeClock()
    es = engines(clock, **{"edge-tts": {}, "kokoro": {}})
    es["edge-tts"].script.append("error503")
    notes = Notes()
    mouth = Mouth(es, ["edge-tts", "kokoro"], notes, clock)  # type: ignore[arg-type]
    assert await speak(mouth, clock, "Hi there.")
    assert es["kokoro"].texts == ["Hi there."]
    st = mouth.state["edge-tts"]
    assert st.reason == "edge-tts returned 503 → switched to kokoro for 10 min"
    assert 599 <= st.open_until - clock.monotonic() <= 600
    await speak(mouth, clock, "Again.")
    assert es["edge-tts"].texts == ["Hi there."]  # skipped while open
    clock.advance(601)
    await speak(mouth, clock, "Back.")
    assert es["edge-tts"].texts[-1] == "Back."


async def test_audio_streams_out_and_reports_first_audio() -> None:
    clock = FakeClock()
    es = engines(clock, kokoro={"latency_s": 0.12})
    notes = Notes()
    seen: list[tuple[str, float | None]] = []
    mouth = Mouth(es, ["kokoro"], notes, clock, observe=lambda n, ms: seen.append((n, ms)))  # type: ignore[arg-type]
    await speak(mouth, clock, "Hello.")
    started, done = notes.of("mouth.started")[0], notes.of("mouth.done")[0]
    assert started["engine"] == "kokoro" and 110 <= started["first_audio_ms"] <= 140
    chunks = notes.of("mouth.audio")
    assert [c["seq"] for c in chunks] == [0, 1]
    assert base64.b64decode(chunks[0]["data"]) == b"ID3fake-audio-1"
    assert done["ok"] is True and seen and seen[0][0] == "kokoro"


async def test_all_engines_failing_degrades_to_text_never_hangs() -> None:
    clock = FakeClock()
    es = engines(clock, kokoro={}, piper={})
    es["kokoro"].script.append("hang")
    es["piper"].script.append("error503")
    notes = Notes()
    mouth = Mouth(es, ["kokoro", "piper"], notes, clock)  # type: ignore[arg-type]
    assert await speak(mouth, clock, "Hello.") is False
    assert notes.of("mouth.done")[-1] == {"utt_id": "u1", "ok": False, "engine": None}
    assert notes.of("watchdog.incident")[-1]["remedy"] == "degrade"


async def test_barge_in_stops_speech_within_150ms() -> None:
    clock = FakeClock()
    es = engines(clock, kokoro={"latency_s": 0.1})
    es["kokoro"].script.append("hang")
    notes = Notes()
    mouth = Mouth(es, ["kokoro"], notes, clock)  # type: ignore[arg-type]
    mouth.start()
    mouth.speak(Utterance("u1", "A long answer."))
    mouth.speak(Utterance("u2", "And more."))
    for _ in range(10):
        await asyncio.sleep(0)
    t0 = clock.monotonic()
    await mouth.stop()
    assert clock.monotonic() - t0 <= 0.15  # cancellation needs no simulated time at all
    assert mouth.queue.empty() and mouth.current is not None and mouth.current.done()
    assert es["kokoro"].texts == ["A long answer."]
    await mouth.close()


def test_budget_is_the_design_number() -> None:
    assert BUDGET_MS["tts"] == 250


async def test_quick_check_benchmarks_an_engine_installed_since_last_run(tmp_path: Any) -> None:
    clock = FakeClock()
    es = engines(clock, kokoro={"latency_s": 0.1, "installed": False}, piper={"latency_s": 0.2})
    await drive(clock, Fitness(es, clock, db_path=tmp_path / "f.db").full())
    es["kokoro"].installed = True  # `uv sync --extra ...` between runs
    fit = Fitness(es, clock, db_path=tmp_path / "f.db")
    assert fit.plan.tts == ["piper"]
    plan = await drive(clock, fit.quick())
    assert plan.tts == ["kokoro", "piper"]
