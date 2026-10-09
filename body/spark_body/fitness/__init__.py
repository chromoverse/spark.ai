"""Device fitness (REDESIGN §18): no engine is used until it has proven, on this device, that it
fits the latency budget. Full suite on first run, a quick probe on every start, a re-probe on
power changes, and a moving average from every real call."""

from __future__ import annotations

import json
import sqlite3
import statistics
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from spark_body.clock import Clock, within
from spark_body.mouth.engines import STANDARD_SENTENCE, TtsEngine, prepare

Role = Literal["tts"]
BUDGET_MS: dict[Role, float] = {"tts": 250.0}  # p95 first audio (§18.3)
FULL_RUNS = 3
PROBE_TIMEOUT_S = 3.0
EWMA = 0.2


@dataclass
class Score:
    engine: str
    role: Role
    p50_ms: float | None
    p95_ms: float | None
    success: float  # 0..1
    expressive: bool
    ewma_ms: float | None = None

    def fits(self) -> bool:
        p95 = self.ewma_ms if self.ewma_ms is not None else self.p95_ms
        return self.success >= 0.99 and p95 is not None and p95 <= BUDGET_MS[self.role]


@dataclass
class Plan:
    tts: list[str] = field(default_factory=list)
    scores: dict[str, Score] = field(default_factory=dict)

    @property
    def degraded(self) -> bool:
        """True when the plan holds only engines over budget (or none at all)."""
        return not any(self.scores[n].fits() for n in self.tts if n in self.scores)

    def wire(self) -> dict[str, Any]:
        """`device.engine_plan` payload for the brain (API.md §3.1)."""
        return {
            "stt": [],
            "tts": self.tts,
            "local_llm": [],
            "scores": {k: asdict(v) for k, v in self.scores.items()},
        }


def _latency(s: Score) -> float:
    return s.ewma_ms if s.ewma_ms is not None else s.p95_ms if s.p95_ms is not None else 1e9


def select(scores: dict[str, Score]) -> list[str]:
    """§18.3: drop what misses the budget, then expressive first, then fastest. If nothing fits,
    the working engines stay in, fastest first: late speech beats silence (§19.2), and the
    brain's heard cue covers the gap."""
    tts = [s for s in scores.values() if s.role == "tts"]
    fit = sorted((s for s in tts if s.fits()), key=lambda s: (not s.expressive, _latency(s)))
    if fit:
        return [s.engine for s in fit]
    working = sorted((s for s in tts if s.success > 0 and s.p95_ms is not None), key=_latency)
    return [s.engine for s in working]


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
    ) -> None:
        self.engines = engines
        self.clock = clock or Clock()
        self.plan = Plan()
        self.on_change = on_change
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
                k: Score(**v) for k, v in saved["scores"].items() if k in self.engines
            }
            self.plan.tts = [n for n in saved["tts"] if n in self.engines]

    def _replan(self) -> None:
        tts = select(self.plan.scores)
        changed = tts != self.plan.tts
        self.plan.tts = tts
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

    async def _bench(self, name: str, runs: int, trigger: str) -> Score:
        engine = self.engines[name]
        times: list[float] = []
        ok = 0
        if engine.available():
            for _ in range(runs):
                ms = await probe_tts(engine, self.clock)
                if ms is not None:
                    ok += 1
                    times.append(ms)
        score = Score(
            name,
            "tts",
            statistics.median(times) if times else None,
            _pct(times, 0.95) if times else None,
            ok / runs if runs else 0.0,
            engine.expressive,
        )
        self._record(trigger, score)
        return score

    async def full(self, trigger: str = "first_run") -> Plan:
        """Every candidate, FULL_RUNS each (onboarding, weekly, "Run benchmark")."""
        for name in self.engines:
            self.plan.scores[name] = await self._bench(name, FULL_RUNS, trigger)
        self._replan()
        return self.plan

    async def quick(self) -> Plan:
        """Every app start (FT2): one probe per selected engine. A selected engine that now
        fails or misses the budget is re-benchmarked fully; stable scores leave the plan alone.
        Engines never measured, or that weren't usable last time but are now (an extra got
        installed, the brain link arrived), get their full benchmark."""
        if not self.plan.scores:
            return await self.full()
        for name, engine in self.engines.items():
            score = self.plan.scores.get(name)
            if (score is None or score.success == 0) and engine.available():
                self.plan.scores[name] = await self._bench(name, FULL_RUNS, "newly_available")
        for name in list(self.plan.tts):
            ms = await probe_tts(self.engines[name], self.clock)
            if ms is None or ms > BUDGET_MS["tts"]:
                self.plan.scores[name] = await self._bench(name, FULL_RUNS, "quick_recheck")
        self._replan()
        return self.plan

    async def power_changed(self) -> Plan:
        """FT3: plugged/unplugged or battery saver → every voice role is re-probed."""
        for name in self.engines:
            self.plan.scores[name] = await self._bench(name, FULL_RUNS, "power_change")
        self._replan()
        return self.plan

    def observe(self, name: str, first_ms: float | None) -> None:
        """Every real call (§18.1 'continuously'): EWMA of first audio; a failure counts as the
        give-up time so a flaky engine drifts out of the plan."""
        s = self.plan.scores.get(name)
        if s is None:
            return
        ms = first_ms if first_ms is not None else PROBE_TIMEOUT_S * 1000
        s.ewma_ms = ms if s.ewma_ms is None else (1 - EWMA) * s.ewma_ms + EWMA * ms
        self._replan()

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT ts, trigger, role, engine, p50_ms, p95_ms, success FROM runs "
            "ORDER BY rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
        keys = ("ts", "trigger", "role", "engine", "p50_ms", "p95_ms", "success")
        return [dict(zip(keys, r, strict=True)) for r in rows]
