"""Speaks reply sentences on the engine plan, switching engines live (REDESIGN §18.4) and
reporting incidents (§19). Audio streams out as chunks; the renderer plays them in order.

Rules per sentence: an engine that errors opens its circuit for 10 min; one that returns no audio
or misses the first-audio budget gets a strike, and two strikes in a row open it. Either way the
same sentence moves to the next engine. Every engine failing → text-only (degrade), never silent."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from spark_body.clock import Clock, within
from spark_body.mouth.engines import TtsEngine, prepare

logger = logging.getLogger(__name__)

BUDGET_S = 0.25  # TTS first audio (§18.3); low-spec devices get fitness.LOW_SPEC_TTS_MS
GIVE_UP_S = 3.0  # an engine with no audio by then has failed this sentence
CIRCUIT_S = 600.0


@dataclass
class EngineState:
    strikes: int = 0
    open_until: float = 0.0
    reason: str = ""  # Engines page: "edge-tts returned 503 → switched to kokoro for 10 min"


@dataclass
class Utterance:
    utt_id: str
    text: str
    tone: str | None = None


Notify = Callable[[str, dict[str, Any]], None]
Observe = Callable[[str, float | None], None]  # engine, first-audio ms (None = failed)


@dataclass
class Mouth:
    engines: dict[str, TtsEngine]
    plan: list[str]
    notify: Notify
    clock: Clock = field(default_factory=Clock)
    observe: Observe | None = None
    budget_s: float = BUDGET_S
    state: dict[str, EngineState] = field(default_factory=dict)
    queue: asyncio.Queue[Utterance] = field(default_factory=asyncio.Queue)
    current: asyncio.Task[bool] | None = None
    worker: asyncio.Task[None] | None = None

    def start(self) -> None:
        self.worker = asyncio.create_task(self._run())

    async def close(self) -> None:
        await self.stop()
        if self.worker is not None:
            self.worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.worker

    def speak(self, utt: Utterance) -> None:
        self.queue.put_nowait(utt)

    async def stop(self) -> None:
        """Barge-in: drop the queue and cut the sentence being synthesized."""
        while not self.queue.empty():
            self.queue.get_nowait()
        if self.current is not None and not self.current.done():
            self.current.cancel()
            await asyncio.wait({self.current})

    async def _run(self) -> None:
        while True:
            utt = await self.queue.get()
            self.current = asyncio.create_task(self.say(utt))
            await asyncio.wait({self.current})

    def _usable(self, name: str) -> bool:
        st = self.state.setdefault(name, EngineState())
        return st.open_until <= self.clock.monotonic() and name in self.engines

    def _strike(self, name: str, why: str, nxt: str | None) -> None:
        st = self.state.setdefault(name, EngineState())
        st.strikes += 1
        if st.strikes >= 2:
            self._open(name, why, nxt)

    def _open(self, name: str, why: str, nxt: str | None) -> None:
        st = self.state.setdefault(name, EngineState())
        st.open_until = self.clock.monotonic() + CIRCUIT_S
        st.strikes = 0
        st.reason = f"{name} {why} → switched to {nxt or 'text only'} for 10 min"

    async def say(self, utt: Utterance) -> bool:
        tried: list[str] = []
        for name in [n for n in self.plan if self._usable(n)]:
            tried.append(name)
            ok, why = await self._attempt(name, utt)
            if ok:
                return True
            nxt = next((n for n in self.plan if n not in tried and self._usable(n)), None)
            self.notify(
                "watchdog.incident",
                {
                    "role": "tts",
                    "engine": name,
                    "error": why,
                    "remedy": "switch" if nxt else "degrade",
                    "outcome": "recovered" if nxt else "degraded",
                    "utt_id": utt.utt_id,
                },
            )
        self.notify("mouth.done", {"utt_id": utt.utt_id, "ok": False, "engine": None})
        return False

    async def _attempt(self, name: str, utt: Utterance) -> tuple[bool, str]:
        engine = self.engines[name]
        t0 = self.clock.monotonic()
        stream = engine.synth(prepare(engine, utt.text, utt.tone), utt.tone)
        seq = 0
        first_ms: float | None = None
        nxt_name = next((n for n in self.plan if n != name and self._usable(n)), None)
        try:
            while True:
                limit = GIVE_UP_S if seq == 0 else GIVE_UP_S * 2
                chunk = await within(self.clock, anext(stream, None), limit)
                if chunk is None:
                    break
                if not chunk:
                    continue
                if seq == 0:
                    first_ms = (self.clock.monotonic() - t0) * 1000
                    self.notify(
                        "mouth.started",
                        {"utt_id": utt.utt_id, "engine": name, "first_audio_ms": round(first_ms)},
                    )
                self.notify(
                    "mouth.audio",
                    {
                        "utt_id": utt.utt_id,
                        "seq": seq,
                        "mime": engine.mime,
                        "data": base64.b64encode(chunk).decode(),
                    },
                )
                seq += 1
        except TimeoutError:
            if seq == 0:
                self._strike(name, "gave no audio in time", nxt_name)
                self._report(name, None)
                return False, "timeout"
            # audio already went out; finish the sentence rather than repeat it elsewhere
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if seq > 0:
                logger.warning("tts broke mid-sentence", extra={"engine": name})
            else:
                why = f"returned {getattr(exc, 'status', None) or type(exc).__name__}"
                self._open(name, why, nxt_name)
                self._report(name, None)
                return False, why
        finally:
            with contextlib.suppress(Exception):
                await stream.aclose()
        if seq == 0:
            self._strike(name, "returned no audio", nxt_name)
            self._report(name, None)
            return False, "empty audio"
        assert first_ms is not None
        st = self.state[name]
        if first_ms > self.budget_s * 1000:
            self._strike(name, f"took {first_ms:.0f} ms to first audio", nxt_name)
        else:
            st.strikes = 0
        self._report(name, first_ms)
        self.notify(
            "mouth.done",
            {"utt_id": utt.utt_id, "ok": True, "engine": name, "first_audio_ms": round(first_ms)},
        )
        return True, ""

    def _report(self, name: str, first_ms: float | None) -> None:
        if self.observe is not None:
            self.observe(name, first_ms)
