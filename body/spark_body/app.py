"""Wires the sidecar's parts to the JSON-RPC methods Electron main calls (API.md §4)."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from spark_body import hands, models
from spark_body.clock import Clock
from spark_body.ear.stt import LocalStt, SttEngine, WhisperProxy
from spark_body.ear.wake import MIN_COMMAND_S, Wake, strip_wake
from spark_body.fitness import Fitness, Plan, Role, budgets, hardware, probe_clip
from spark_body.hands.apps import INDEX, AppIndex
from spark_body.mouth.engines import BrainLink, EdgeTts, LocalTts, OrpheusProxy, TtsEngine
from spark_body.mouth.speaker import Mouth, Utterance
from spark_body.reflex_arc import Phrases, decide
from spark_body.rpc import INVALID_PARAMS, Rpc, RpcError

UNAVAILABLE = -32000  # JSON-RPC server error: no engine could do it

logger = logging.getLogger(__name__)

VERSION = "0.1.0"
POWER_POLL_S = 30.0


def data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") if sys.platform == "win32" else None
    root = Path(base) if base else Path.home() / ".local" / "share"
    path = root / "SparkAI"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _need(params: dict[str, Any], key: str, kind: type) -> Any:
    value = params.get(key)
    if not isinstance(value, kind):
        raise RpcError(INVALID_PARAMS, f"{key} must be {kind.__name__}")
    return value


@dataclass
class Body:
    rpc: Rpc
    engines: dict[str, TtsEngine]
    clock: Clock = field(default_factory=Clock)
    db_path: Path | None = None
    phrases: Phrases = field(default_factory=Phrases)
    last_said: list[str] = field(default_factory=list)
    link: BrainLink = field(default_factory=BrainLink)
    ears: dict[str, SttEngine] = field(default_factory=dict)
    wake: Wake | None = None
    budget: dict[Role, float] | None = None
    models_root: Path | None = None
    downloads: dict[str, dict[str, Any]] = field(default_factory=dict)  # Engines page

    def __post_init__(self) -> None:
        self.fitness = Fitness(
            self.engines, self.clock, self.db_path, self._plan_changed, self.ears, self.budget
        )
        self.mouth = Mouth(
            self.engines,
            list(self.fitness.plan.tts),
            self.rpc.notify,
            self.clock,
            observe=self.fitness.observe,
            budget_s=self.fitness.plan.budget["tts"] / 1000,
        )
        self._register()

    def _plan_changed(self, plan: Plan) -> None:
        self.mouth.plan = list(plan.tts)
        self.rpc.notify("engine.plan", plan.wire())

    def speak(self, utt_id: str, text: str, tone: str | None = None) -> None:
        if text:
            self.last_said = [*self.last_said[-9:], text]
            self.mouth.speak(Utterance(utt_id, text, tone))

    async def handle(self, text: str, verbosity: str = "normal") -> dict[str, Any]:
        """Tier 0 (§26.4-A): decide, act, answer. `handled: false` → send it to the brain."""
        m = decide(text, INDEX.spoken())
        if m is None:
            return {"handled": False}
        if m.intent == "stop":
            await self.mouth.stop()
            return {"handled": True, "intent": "stop", "interrupt": True}
        if m.intent == "repeat":
            if not self.last_said:
                return {"handled": False}  # nothing to repeat: let the brain answer
            self.speak("repeat", self.last_said[-1])
            return {"handled": True, "intent": "repeat", "record": False}
        output: dict[str, Any] = {}
        result: dict[str, Any]
        if m.intent in hands.HANDS:
            try:
                output = await hands.run(m.intent, m.slots)
            except hands.ToolFailure as exc:
                # A3: the brain takes over with the error and offers an alternative
                result = {"ok": False, "error": {"code": exc.code, "message": exc.message}}
                return {"handled": True, "intent": m.intent, "slots": m.slots, "result": result}
        said = self.phrases.reply(m, output, datetime.now(), chatty=verbosity == "detailed")
        if said:
            self.speak(f"t0-{m.intent}", said)
        result = {"ok": True, "said": said or None, "output": output or None}
        return {
            "handled": True,
            "intent": m.intent,
            "slots": m.slots,
            "result": result,
            "chime": not said,
        }

    def stt_plan(self) -> list[str]:
        """The fitness plan's order, then any usable engine it hasn't measured yet."""
        ready = [n for n, e in self.ears.items() if e.available()]
        planned = [n for n in self.fitness.plan.stt if n in ready]
        return planned + [n for n in ready if n not in planned]

    async def fetch_models(self, hw: dict[str, Any]) -> bool:
        """Downloads the models this device's tier wants, one at a time, in the background.
        True if any arrived (they then get benchmarked). A failure is reported and retried on
        the next start; the cloud engines cover until then."""
        if self.models_root is None or not models.runtime():
            return False
        loop = asyncio.get_running_loop()
        arrived = False
        for m in models.wanted(hw):
            state: dict[str, Any] = {"role": m.role, "mb": m.mb, "pct": 0, "state": "downloading"}
            self.downloads[m.name] = state
            if models.installed(self.models_root, m.name) is not None:
                state.update(pct=100, state="ready")
                continue

            def progress(done: int, total: int, name: str = m.name, st: Any = state) -> None:
                pct = done * 100 // total if total else 0
                if pct >= st["pct"] + 10:  # every 10%; runs on the download thread
                    st["pct"] = pct
                    note = {"name": name, "pct": pct}
                    loop.call_soon_threadsafe(self.rpc.notify, "models.progress", note)

            try:
                await asyncio.to_thread(models.fetch, m, self.models_root, progress)
            except Exception as exc:
                logger.warning("model %s didn't download: %s", m.name, exc)
                state.update(state="failed", error=str(exc)[:200])
                self.rpc.notify(
                    "watchdog.incident",
                    {
                        "role": m.role,
                        "engine": m.name,
                        "error": f"download failed: {type(exc).__name__}",
                        "remedy": "retry_next_start",
                        "outcome": "degraded",
                    },
                )
                continue
            state.update(pct=100, state="ready")
            self.rpc.notify("models.progress", {"name": m.name, "pct": 100})
            arrived = True
        return arrived

    async def warm_ear(self) -> None:
        """Load the wake spotter and the plan's first STT model before the user speaks: each
        costs ~1.2 s on its first call."""
        head = [self.ears[n] for n in self.stt_plan()[:1]]
        for part in [self.wake, *head]:
            if part is not None and part.available() and hasattr(part, "warm"):
                try:
                    await part.warm()
                except Exception:
                    logger.exception("couldn't load %s", getattr(part, "name", part))

    async def warm_up(self, hw: dict[str, Any]) -> None:
        await self.warm_ear()
        await self.fitness.quick()  # FT2: every start
        if await self.fetch_models(hw):
            await self.fitness.quick()  # benchmarks what just arrived
            await self.warm_ear()

    async def watch_power(self) -> None:
        last = hardware.power()
        while True:
            await self.clock.sleep(POWER_POLL_S)
            now = await asyncio.to_thread(hardware.power)
            if (now["plugged"], now["saver"]) != (last["plugged"], last["saver"]):
                logger.info("power changed, re-probing engines")
                await self.fitness.power_changed()
            last = now

    def _register(self) -> None:
        r = self.rpc

        @r.method("hello")
        async def hello(_: dict[str, Any]) -> dict[str, Any]:
            return {
                "version": VERSION,
                "hardware": await asyncio.to_thread(hardware.scan),
                "capabilities": sorted({"apps", "media", "volume", "brightness", "tts"}),
                "engine_plan": self.fitness.plan.wire(),
            }

        @r.method("reflex.handle")
        async def reflex_handle(p: dict[str, Any]) -> dict[str, Any]:
            return await self.handle(_need(p, "text", str), str(p.get("verbosity", "normal")))

        @r.method("tool.run")
        async def tool_run(p: dict[str, Any]) -> dict[str, Any]:
            try:
                output = await hands.run(_need(p, "tool", str), _need(p, "input", dict))
            except hands.ToolFailure as exc:
                return {"ok": False, "error": {"code": exc.code, "message": exc.message}}
            return {"ok": True, "output": output}

        @r.method("tts.speak")
        async def tts_speak(p: dict[str, Any]) -> dict[str, Any]:
            tone = p.get("tone")
            self.speak(
                _need(p, "utt_id", str),
                _need(p, "text", str),
                tone if isinstance(tone, str) else None,
            )
            return {"queued": True}

        @r.method("tts.stop")
        async def tts_stop(_: dict[str, Any]) -> dict[str, Any]:
            await self.mouth.stop()
            return {"stopped": True}

        @r.method("fitness.run")
        async def fitness_run(_: dict[str, Any]) -> dict[str, Any]:
            return (await self.fitness.full("on_demand")).wire()

        @r.method("fitness.quick")
        async def fitness_quick(_: dict[str, Any]) -> dict[str, Any]:
            return (await self.fitness.quick()).wire()

        @r.method("engine.plan")
        async def engine_plan(_: dict[str, Any]) -> dict[str, Any]:
            reasons = {k: v.reason for k, v in self.mouth.state.items() if v.reason}
            return self.fitness.plan.wire() | {
                "reasons": reasons,
                "history": self.fitness.history(),
                "budget_ms": self.fitness.plan.budget,
                "models": self.downloads,
                "wake": self.wake is not None and self.wake.available(),
            }

        @r.method("stt.transcribe")
        async def stt_transcribe(p: dict[str, Any]) -> dict[str, Any]:
            """One endpointed utterance (16-bit mono PCM, base64) → text, on the first STT
            engine in the plan that answers. An empty transcript is a result, not an error.
            `wake: true`: the utterance must hold the wake word. Without it nothing is
            transcribed (`wake: false` back); with it, STT hears only what follows the phrase,
            and just the phrase gives `text: ""` with `wake: true` (the renderer then listens
            for the command). `wake: null` back: this device can't spot it yet (model still
            downloading), so it was transcribed like an open mic."""
            pcm = base64.b64decode(_need(p, "pcm16", str))
            rate = int(p.get("sample_rate", 16000))
            wake: bool | None = None
            if p.get("wake") is True and self.wake is not None and self.wake.available():
                cut = await self.wake.find(pcm, rate)
                wake = cut is not None
                if cut is None:
                    return {"text": "", "wake": False}
                pcm = pcm[cut * 2 :]
                if len(pcm) / 2 / rate < MIN_COMMAND_S:
                    return {"text": "", "wake": True}
            plan = self.stt_plan()
            if not plan:
                raise RpcError(UNAVAILABLE, "No speech engine is ready. Sign in or install one.")
            probe_pcm, probe_rate = probe_clip()
            # latency grows with audio length: score long utterances at the probe's length
            scale = min(1.0, (len(probe_pcm) / probe_rate) / max(1e-3, len(pcm) / 2 / rate))
            for name in plan:
                t0 = self.clock.monotonic()
                try:
                    heard = await self.ears[name].transcribe(pcm, rate)
                except Exception as exc:
                    self.fitness.observe(name, None)
                    self.rpc.notify(
                        "watchdog.incident",
                        {
                            "role": "stt",
                            "engine": name,
                            "error": type(exc).__name__,
                            "remedy": "switch",
                            "outcome": "recovered",
                        },
                    )
                    continue
                ms = round((self.clock.monotonic() - t0) * 1000)
                self.fitness.observe(name, ms * scale)
                return {
                    "text": strip_wake(heard.text) if wake else heard.text,
                    "lang": heard.lang,
                    "engine": name,
                    "stt_ms": ms,
                    "wake": wake,
                }
            raise RpcError(UNAVAILABLE, "I couldn't make that out. Try again?")

        @r.method("auth.set")
        async def auth_set(p: dict[str, Any]) -> dict[str, Any]:
            """Brain URL + access token for cloud voice engines (memory only, never logged)."""
            fresh = not self.link.token
            self.link.url = _need(p, "brain_url", str).rstrip("/")
            self.link.token = _need(p, "access_token", str)
            if fresh:  # a cloud engine just became available: give it its benchmark now
                task = asyncio.create_task(self.fitness.full("cloud_link"))
                self.rpc.tasks.add(task)
                task.add_done_callback(self.rpc.tasks.discard)
            return {"ok": True}

        @r.method("apps.refresh")
        async def apps_refresh(_: dict[str, Any]) -> dict[str, Any]:
            fresh = await asyncio.to_thread(AppIndex.scan)
            INDEX.entries = fresh.entries
            return {"apps": len(INDEX.entries)}


async def main() -> None:
    logging.basicConfig(
        stream=sys.stderr, level=logging.INFO, format="%(levelname)s %(name)s %(message)s"
    )
    rpc = Rpc()
    link = BrainLink()
    hw = await asyncio.to_thread(hardware.scan)
    tier = models.tier(hw)
    root = data_dir() / "models"
    mine = models.wanted(hw)  # this device's on-device models (downloaded in warm_up)
    engines: dict[str, TtsEngine] = {"groq-orpheus": OrpheusProxy(link), "edge-tts": EdgeTts()}
    engines |= {m.name: LocalTts(m, root) for m in mine if m.role == "tts"}
    ears: dict[str, SttEngine] = {m.name: LocalStt(m, root) for m in mine if m.role == "stt"}
    ears["groq-whisper"] = WhisperProxy(link)
    body = Body(
        rpc,
        engines,
        db_path=data_dir() / "fitness.db",
        link=link,
        ears=ears,
        wake=Wake(root),
        budget=budgets(tier),
        models_root=root,
    )
    logger.info("hardware tier %s, on-device models: %s", tier, [m.name for m in mine])
    body.mouth.start()
    INDEX.entries = (await asyncio.to_thread(AppIndex.scan)).entries
    background = [
        asyncio.create_task(body.warm_up(hw)),
        asyncio.create_task(body.watch_power()),
    ]
    rpc.notify("body.ready", {"version": VERSION})
    try:
        await rpc.serve()
    finally:
        for task in background:
            task.cancel()
        await body.mouth.close()
