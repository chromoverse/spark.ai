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

from spark_body import hands
from spark_body.clock import Clock
from spark_body.ear.stt import SttEngine, WhisperProxy
from spark_body.fitness import Fitness, Plan, hardware
from spark_body.hands.apps import INDEX, AppIndex
from spark_body.mouth.engines import BrainLink, EdgeTts, OrpheusProxy, TtsEngine
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

    def __post_init__(self) -> None:
        self.fitness = Fitness(self.engines, self.clock, self.db_path, self._plan_changed)
        self.mouth = Mouth(
            self.engines,
            list(self.fitness.plan.tts),
            self.rpc.notify,
            self.clock,
            observe=self.fitness.observe,
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
            }

        @r.method("stt.transcribe")
        async def stt_transcribe(p: dict[str, Any]) -> dict[str, Any]:
            """One endpointed utterance (16-bit mono PCM, base64) → text, on the first STT
            engine in the plan that answers. An empty transcript is a result, not an error."""
            pcm = base64.b64decode(_need(p, "pcm16", str))
            rate = int(p.get("sample_rate", 16000))
            plan = [n for n, e in self.ears.items() if e.available()]
            if not plan:
                raise RpcError(UNAVAILABLE, "No speech engine is ready. Sign in or install one.")
            for name in plan:
                t0 = self.clock.monotonic()
                try:
                    heard = await self.ears[name].transcribe(pcm, rate)
                except Exception as exc:
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
                return {"text": heard.text, "lang": heard.lang, "engine": name, "stt_ms": ms}
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
    engines: dict[str, TtsEngine] = {"groq-orpheus": OrpheusProxy(link), "edge-tts": EdgeTts()}
    body = Body(
        rpc,
        engines,
        db_path=data_dir() / "fitness.db",
        link=link,
        ears={"groq-whisper": WhisperProxy(link)},
    )
    body.mouth.start()
    INDEX.entries = (await asyncio.to_thread(AppIndex.scan)).entries
    background = [
        asyncio.create_task(body.fitness.quick()),  # FT2: every start
        asyncio.create_task(body.watch_power()),
    ]
    rpc.notify("body.ready", {"version": VERSION})
    try:
        await rpc.serve()
    finally:
        for task in background:
            task.cancel()
        await body.mouth.close()
