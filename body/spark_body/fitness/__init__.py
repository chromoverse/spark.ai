"""Device fitness (REDESIGN §18): no engine is used until it has proven, on this device, that it
fits the latency budget. Full suite on first run, a quick probe on every start, a re-probe on
power changes, and a moving average from every real call. Covers TTS and STT."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
import statistics
import wave
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from functools import cache
from pathlib import Path
from typing import Any, Literal

from spark_body.clock import Clock, within
from spark_body.ear.stt import SttEngine
from spark_body.mouth.engines import STANDARD_SENTENCE, TtsEngine, prepare

logger = logging.getLogger(__name__)

Role = Literal["tts", "stt"]
BUDGET_MS: dict[Role, float] = {"tts": 250.0, "stt": 300.0}  # p95 (§18.3)
# Low-spec devices (models.tier 0) aim for first audio within 2 s instead of 1 s (owner's call,
# 2026-10-10): the expressive cloud voice (~650 ms per sentence) still fits there.
LOW_SPEC_TTS_MS = 700.0
# ...and STT: a cloud model that hears far better (Groq Whisper ~80% vs Moonshine-tiny ~70% words
# right on short commands, ~300 ms) is worth its extra ~150 ms there.
LOW_SPEC_STT_MS = 700.0
FULL_RUNS = 3
PROBE_TIMEOUT_S = 3.0
EWMA = 0.2

PROBE_WAV = Path(__file__).resolve().parent.parent / "ear" / "probe.wav"
PROBE_TEXT = "Turn the volume up to thirty, then play some music."  # a command, wake phrase cut
# Accuracy: short commands in four voices with light noise. The one-voice probe was too easy: every
# engine scored 90% there, so accuracy never decided anything.
ACCURACY_WAV = PROBE_WAV.with_name("accuracy.wav")
ACCURACY_TEXT = (
    "Tell me a joke. Set brightness to fifty percent. Open Spotify and play something calm. "
    "What's the weather like in Kathmandu?"
)
ACCURACY_TIMEOUT_S = 10.0


def budgets(tier: int) -> dict[Role, float]:
    low: dict[Role, float] = {"tts": LOW_SPEC_TTS_MS, "stt": LOW_SPEC_STT_MS}
    return low if tier == 0 else dict(BUDGET_MS)


@dataclass
class Score:
    engine: str
    role: Role
    p50_ms: float | None
    p95_ms: float | None
    success: float  # 0..1
    expressive: bool
    ewma_ms: float | None = None
    accuracy: float | None = None  # STT: 1 - word error rate on the probe clip

    def fits(self, budget: Mapping[Role, float]) -> bool:
        p95 = self.ewma_ms if self.ewma_ms is not None else self.p95_ms
        return self.success >= 0.99 and p95 is not None and p95 <= budget[self.role]


@dataclass
class Plan:
    tts: list[str] = field(default_factory=list)
    stt: list[str] = field(default_factory=list)
    scores: dict[str, Score] = field(default_factory=dict)
    budget: dict[Role, float] = field(default_factory=lambda: dict(BUDGET_MS))

    @property
    def degraded(self) -> bool:
        """True when the TTS plan holds only engines over budget (or none at all)."""
        return not any(self.scores[n].fits(self.budget) for n in self.tts if n in self.scores)

    def wire(self) -> dict[str, Any]:
        """`device.engine_plan` payload for the brain (API.md §3.1)."""
        return {
            "stt": self.stt,
            "tts": self.tts,
            "local_llm": [],
            "scores": {k: asdict(v) for k, v in self.scores.items()},
        }


def _latency(s: Score) -> float:
    return s.ewma_ms if s.ewma_ms is not None else s.p95_ms if s.p95_ms is not None else 1e9


def _fold(s: Score, ms: float) -> None:
    s.ewma_ms = ms if s.ewma_ms is None else (1 - EWMA) * s.ewma_ms + EWMA * ms


def _working(scores: list[Score]) -> list[Score]:
    return sorted((s for s in scores if s.success > 0 and s.p95_ms is not None), key=_latency)


def select(scores: dict[str, Score], budget: Mapping[Role, float] = BUDGET_MS) -> list[str]:
    """§18.3 TTS: what fits the budget, expressive first, then fastest. Every other working
    engine follows as a fallback, fastest first: late speech beats silence (§19.2), and the
    brain's heard cue covers the gap."""
    tts = [s for s in scores.values() if s.role == "tts"]
    fit = sorted((s for s in tts if s.fits(budget)), key=lambda s: (not s.expressive, _latency(s)))
    return [s.engine for s in [*fit, *(s for s in _working(tts) if s not in fit)]]


def select_stt(scores: dict[str, Score], budget: Mapping[Role, float] = BUDGET_MS) -> list[str]:
    """§18.3 STT: what fits, most accurate first (accuracy in 5% steps, then fastest); then every
    other working engine as a fallback, fastest first: being heard late beats not being heard."""
    stt = [s for s in scores.values() if s.role == "stt"]
    fit = sorted(
        (s for s in stt if s.fits(budget)),
        key=lambda s: (-round((s.accuracy or 0) * 20), _latency(s)),
    )
    rest = [s for s in _working(stt) if s not in fit]
    return [s.engine for s in [*fit, *rest]]


async def probe_tts(engine: TtsEngine, clock: Clock) -> float | None:
    """ms to the first audio chunk of the standard sentence; None if it failed or gave nothing."""
    t0 = clock.monotonic()
    stream = engine.synth(prepare(engine, STANDARD_SENTENCE, None), None)
    try:
        while True:
            chunk = await within(clock, anext(stream, None), PROBE_TIMEOUT_S)
            if chunk is None:
                return None
            if chunk:
                return (clock.monotonic() - t0) * 1000
    except Exception:
        return None
    finally:
        await stream.aclose()


def _words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9' ]", " ", text.lower()).split()


def accuracy(expected: str, heard: str) -> float:
    """1 - word error rate (edit distance over words), floored at 0."""
    a, b = _words(expected), _words(heard)
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, y in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (x != y))
    return max(0.0, 1 - row[len(b)] / max(1, len(a)))


def _read(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as w:
        return w.readframes(w.getnframes()), w.getframerate()


@cache
def probe_clip() -> tuple[bytes, int]:
    return _read(PROBE_WAV)


@cache
def accuracy_clip() -> tuple[bytes, int]:
    return _read(ACCURACY_WAV)


async def stt_accuracy(engine: SttEngine, clock: Clock) -> float | None:
    """1 - WER on the accuracy clip; None if the engine failed on it."""
    pcm, rate = accuracy_clip()
    try:
        heard = await within(clock, engine.transcribe(pcm, rate), ACCURACY_TIMEOUT_S)
    except Exception:
        return None
    return accuracy(ACCURACY_TEXT, heard.text)


async def probe_stt(engine: SttEngine, clock: Clock) -> tuple[float, float] | None:
    """(ms to the transcript of the probe clip, accuracy); None if it failed or heard nothing."""
    pcm, rate = probe_clip()
    t0 = clock.monotonic()
    try:
        heard = await within(clock, engine.transcribe(pcm, rate), PROBE_TIMEOUT_S)
    except Exception:
        return None
    if not heard.text.strip():
        return None
    return (clock.monotonic() - t0) * 1000, accuracy(PROBE_TEXT, heard.text)


def _pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


class Fitness:
    def __init__(
        self,
        engines: dict[str, TtsEngine],
        clock: Clock | None = None,
        db_path: Path | None = None,
        on_change: Callable[[Plan], None] | None = None,
        ears: dict[str, SttEngine] | None = None,
        budget: dict[Role, float] | None = None,
    ) -> None:
        self.engines = engines
        self.ears = ears if ears is not None else {}
        self.clock = clock or Clock()
        self.plan = Plan(budget=budget or dict(BUDGET_MS))
        self.on_change = on_change
        # one run at a time: the brain-link benchmark landed on top of the start-up check and
        # both measured a busy CPU (Piper read 500 ms instead of ~180; owner's laptop, 2026-10-10)
        self._running = asyncio.Lock()
        self.db = sqlite3.connect(db_path or ":memory:", check_same_thread=False)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS runs (ts REAL, trigger TEXT, role TEXT, engine TEXT, "
            "p50_ms REAL, p95_ms REAL, success REAL, expressive INTEGER)"
        )
        self.db.execute("CREATE TABLE IF NOT EXISTS plan (id INTEGER PRIMARY KEY, body TEXT)")
        row = self.db.execute("SELECT body FROM plan WHERE id = 1").fetchone()
        if row is not None:  # last known scores: the start-up quick check builds on them
            saved = json.loads(row[0])
            self.plan.scores = {
                k: Score(**v) for k, v in saved["scores"].items() if k in self._all()
            }
            self.plan.tts = [n for n in saved["tts"] if n in self.engines]
            self.plan.stt = [n for n in saved.get("stt", []) if n in self.ears]

    def _all(self) -> dict[str, TtsEngine | SttEngine]:
        return {**self.engines, **self.ears}

    def _replan(self) -> None:
        tts = select(self.plan.scores, self.plan.budget)
        stt = select_stt(self.plan.scores, self.plan.budget)
        changed = (tts, stt) != (self.plan.tts, self.plan.stt)
        self.plan.tts, self.plan.stt = tts, stt
        self.db.execute(
            "INSERT OR REPLACE INTO plan (id, body) VALUES (1, ?)", (json.dumps(self.plan.wire()),)
        )
        self.db.commit()
        if changed and self.on_change is not None:
            self.on_change(self.plan)

    def _record(self, trigger: str, s: Score) -> None:
        self.db.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                self.clock.monotonic(),
                trigger,
                s.role,
                s.engine,
                s.p50_ms,
                s.p95_ms,
                s.success,
                int(s.expressive),
            ),
        )

    async def _probe(self, name: str) -> tuple[float, float | None] | None:
        if name in self.engines:
            ms = await probe_tts(self.engines[name], self.clock)
            return None if ms is None else (ms, None)
        return await probe_stt(self.ears[name], self.clock)

    async def _bench(self, name: str, runs: int, trigger: str) -> Score:
        engine = self._all()[name]
        times: list[float] = []
        accs: list[float] = []
        if engine.available():
            if (warm := getattr(engine, "warm", None)) is not None:  # local models: load first
                try:
                    await warm()
                except Exception:
                    logger.exception("%s failed to load", name)
            else:  # cloud engines: an untimed call first (a cold first call pays for connections)
                await self._probe(name)
            for _ in range(runs):
                got = await self._probe(name)
                if got is not None:
                    times.append(got[0])
                    if got[1] is not None:
                        accs.append(got[1])
            if times and name in self.ears:
                acc = await stt_accuracy(self.ears[name], self.clock)
                accs = [acc] if acc is not None else accs
        score = Score(
            name,
            "tts" if name in self.engines else "stt",
            statistics.median(times) if times else None,
            _pct(times, 0.95) if times else None,
            len(times) / runs if runs else 0.0,
            bool(getattr(engine, "expressive", False)),
            accuracy=min(accs) if accs else None,
        )
        self._record(trigger, score)
        return score

    async def full(self, trigger: str = "first_run") -> Plan:
        """Every candidate, FULL_RUNS each (onboarding, weekly, "Run benchmark")."""
        async with self._running:
            return await self._full(trigger)

    async def _full(self, trigger: str) -> Plan:
        for name in self._all():
            self.plan.scores[name] = await self._bench(name, FULL_RUNS, trigger)
        self._replan()
        return self.plan

    async def quick(self) -> Plan:
        """Every app start (FT2): one probe per engine that fits (and the first STT engine). One
        that now fails or misses the budget is re-benchmarked fully; a good probe is folded into
        its moving average. Fallbacks over budget are left alone (no quota spent on them).
        Engines never measured, or that weren't usable last time but are now (an extra got
        installed, a model finished downloading, the brain link arrived), get their full
        benchmark. One slow call of three can push a good engine's p95 over budget for good (a
        demoted engine isn't used, so live calls never fix it): one whose median fits gets a probe
        too, and a good one brings it back."""
        async with self._running:
            if not self.plan.scores:
                return await self._full("first_run")
            return await self._quick()

    async def _quick(self) -> Plan:
        for name, engine in self._all().items():
            score = self.plan.scores.get(name)
            if (score is None or score.success == 0) and engine.available():
                self.plan.scores[name] = await self._bench(name, FULL_RUNS, "newly_available")
        budget = self.plan.budget
        fitting = [n for n in self.plan.tts if self.plan.scores[n].fits(budget)]
        near = [
            n
            for n, s in self.plan.scores.items()
            if not s.fits(budget) and s.success > 0 and (s.p50_ms or 1e9) <= budget[s.role]
        ]
        for name in dict.fromkeys([*fitting, *self.plan.stt[:1], *near]):
            got = await self._probe(name)
            role: Role = "tts" if name in self.engines else "stt"
            if got is not None and got[0] <= budget[role]:
                _fold(self.plan.scores[name], got[0])
            elif name not in near:
                self.plan.scores[name] = await self._bench(name, FULL_RUNS, "quick_recheck")
        self._replan()
        return self.plan

    async def power_changed(self) -> Plan:
        """FT3: plugged/unplugged or battery saver → every voice role is re-probed."""
        async with self._running:
            return await self._full("power_change")

    def observe(self, name: str, first_ms: float | None) -> None:
        """Every real call (§18.1 'continuously'): EWMA of first audio (TTS) or transcript (STT);
        a failure counts as the give-up time so a flaky engine drifts out of the plan."""
        s = self.plan.scores.get(name)
        if s is None:
            return
        _fold(s, first_ms if first_ms is not None else PROBE_TIMEOUT_S * 1000)
        self._replan()

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT ts, trigger, role, engine, p50_ms, p95_ms, success FROM runs "
            "ORDER BY rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
        keys = ("ts", "trigger", "role", "engine", "p50_ms", "p95_ms", "success")
        return [dict(zip(keys, r, strict=True)) for r in rows]
