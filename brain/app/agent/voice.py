"""The voice loop in the brain (REDESIGN §4.1, §26.4 A to C): signal in → tier 1 or reflex →
reply.delta / reply.cue / tool.call out. Every signal gets a supervisor watch and ends answered,
cancelled, or explained (§19.2)."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Literal

from pydantic import ValidationError

from app.agent import context, persona, reflex
from app.agent.context import Context
from app.core.clock import within
from app.core.runtime import Runtime
from app.core.security import Principal
from app.gateway import live
from app.gateway.signals import (
    EngineIncident,
    SignalFinal,
    SignalHandledLocally,
    SignalInterrupt,
    SignalPartial,
    SignalTrace,
    ToolResult,
)
from app.router import tier1
from app.supervisor.watch import Supervisor, Watch
from app.tools.spec import ToolSpec

logger = logging.getLogger(__name__)

PREFETCH_TTL_S = 30.0
Cue = Literal["heard", "done", "error"]


class Voice:
    def __init__(self, rt: Runtime) -> None:
        self.rt = rt
        self.sup = Supervisor(rt, self.explain)
        # ponytail: in-process maps. A tool.result comes back on the socket that got the
        # tool.call, i.e. this process; cross-device calls (R2) move this to Redis pub/sub.
        self.calls: dict[str, tuple[uuid.UUID, asyncio.Future[ToolResult]]] = {}
        self.prefetch: dict[tuple[uuid.UUID, str], tuple[float, asyncio.Task[Context]]] = {}
        self.tasks: set[asyncio.Task[Any]] = set()

    def _spawn(self, coro: Any) -> asyncio.Task[Any]:
        task: asyncio.Task[Any] = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    # ── device → brain ────────────────────────────────────────────────────────────────────

    async def partial(self, p: Principal, msg: SignalPartial) -> dict[str, Any]:
        """Prefetch the turn context while the user is still talking (§4.2)."""
        now = self.rt.clock.monotonic()
        for key, (t, task) in list(self.prefetch.items()):
            if now - t > PREFETCH_TTL_S:
                task.cancel()
                del self.prefetch[key]
        key = (p.user_id, msg.signal_id)
        if key not in self.prefetch:
            task = asyncio.create_task(context.load(self.rt, p.user_id, p.device_id))
            self.prefetch[key] = (now, task)
        return {"signal_id": msg.signal_id}

    async def _context(self, p: Principal, signal_id: str) -> Context:
        hit = self.prefetch.pop((p.user_id, signal_id), None)
        if hit is not None:
            try:
                return await hit[1]
            except Exception:
                logger.warning("prefetch failed", exc_info=True)
        return await context.load(self.rt, p.user_id, p.device_id)

    async def final(self, p: Principal, msg: SignalFinal) -> dict[str, Any]:
        w = await self.sup.open(p.user_id, p.device_id, msg.signal_id)
        if w is None:
            return {"signal_id": msg.signal_id, "duplicate": True}
        intent = tier1.classify(msg.text)
        w.tier = 1 if intent else 2
        if intent is not None:
            w.task = self._spawn(self._tier1(p, w, msg, intent))
        else:
            w.task = self._spawn(self._reflex(p, w, msg.text, msg.utc_offset_min, None))
            self._spawn(self.sup.heard_cue(w, lambda: self.cue(w, "heard")))
        self.sup.mark(w, "ack")
        return {"signal_id": msg.signal_id, "tier": w.tier}

    async def handled_locally(self, p: Principal, msg: SignalHandledLocally) -> dict[str, Any]:
        """Tier 0 ran on the device (§27). Success: record it. Failure: the reflex LLM takes it
        as if it had come here first, with the device's error (A3)."""
        w = await self.sup.open(p.user_id, p.device_id, msg.signal_id)
        if w is None:
            return {"signal_id": msg.signal_id, "duplicate": True}
        use_id = f"local_{msg.signal_id}"[:64]
        said = [{"type": "text", "text": msg.result.said}] if msg.result.said else []
        use = {"type": "tool_use", "id": use_id, "name": msg.intent, "input": msg.slots}
        outcome = (
            reflex.tool_content(msg.result.output if msg.result.output is not None else "ok")
            if msg.result.ok
            else msg.result.error.message
            if msg.result.error
            else "failed"
        )
        result = {
            "type": "tool_result",
            "tool_use_id": use_id,
            "content": outcome,
            "is_error": not msg.result.ok,
        }
        if msg.result.ok:
            w.tier = 0
            w.task = self._spawn(self._store_local(p, w, msg.text, said, use, result))
            return {"signal_id": msg.signal_id, "tier": 0}
        after: list[dict[str, Any]] = [
            {"role": "assistant", "content": [*said, use]},
            {"role": "user", "content": [result]},
        ]
        w.task = self._spawn(self._reflex(p, w, msg.text, msg.utc_offset_min, after))
        return {"signal_id": msg.signal_id, "tier": 2}

    async def interrupt(self, p: Principal, msg: SignalInterrupt) -> dict[str, Any]:
        """Barge-in or a cancelled speculative start: stop the turn; the device already
        stopped its audio."""
        w = (
            self.sup.get(p.user_id, msg.signal_id)
            if msg.signal_id
            else self.sup.latest(p.user_id, p.device_id)
        )
        if w is None:
            return {"cancelled": None}
        await self.sup.cancel(w)
        return {"cancelled": w.signal_id}

    async def tool_result(self, p: Principal, msg: ToolResult) -> dict[str, Any]:
        entry = self.calls.get(msg.call_id)
        if entry is None or entry[0] != p.user_id:
            return {"accepted": False}  # late, unknown, or another user's call
        if not entry[1].done():
            entry[1].set_result(msg)
        return {"accepted": True}

    async def trace(self, p: Principal, msg: SignalTrace) -> dict[str, Any]:
        logger.info(
            "signal trace",
            extra={
                "signal_id": msg.signal_id,
                "device_spans": msg.spans,
                "stt": msg.stt_engine,
                "tts": msg.tts_engine,
            },
        )
        return {}

    async def engine_incident(self, p: Principal, msg: EngineIncident) -> dict[str, Any]:
        await self.sup.incident(
            None,
            user_id=p.user_id,
            device_id=p.device_id,
            stage=msg.role,
            engine=msg.engine,
            error=msg.error,
            remedy=msg.remedy,
            outcome=msg.outcome,
        )
        return {}

    # ── turn runners ──────────────────────────────────────────────────────────────────────

    async def _reflex(
        self,
        p: Principal,
        w: Watch,
        text: str,
        utc_offset_min: int | None,
        after: list[dict[str, Any]] | None,
    ) -> None:
        try:
            ctx = await self._context(p, w.signal_id)
            await reflex.run(self, w, ctx, text, utc_offset_min=utc_offset_min, after=after)
        except asyncio.CancelledError:
            # ponytail: a cancelled turn isn't stored; keep the spoken part if history needs it
            raise
        except Exception:
            logger.error("reflex turn failed", exc_info=True)
            if w.state == "open":
                await self.fail(w, "failure", stage="brain", error="reflex crashed")

    async def _tier1(self, p: Principal, w: Watch, msg: SignalFinal, intent: tier1.Intent) -> None:
        ctx = await self._context(p, w.signal_id)
        if intent.kind == "stop":
            for other in [o for o in self.sup.watches.values() if o.user_id == p.user_id]:
                if other is not w:
                    await self.sup.cancel(other)
            reply = await persona.phrase(self.rt.redis, p.user_id, "ack")
        else:
            reply = tier1.language_reply(intent.value or "", ctx.language)
        await self.delta(w, reply)
        await self.store(
            w,
            ctx,
            [
                ("user", [{"type": "text", "text": msg.text}]),
                ("assistant", [{"type": "text", "text": reply}]),
            ],
        )
        self.sup.finish(w, "answered")
        await self.end(w)

    async def _store_local(
        self,
        p: Principal,
        w: Watch,
        text: str,
        said: list[dict[str, Any]],
        use: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        ctx = await self._context(p, w.signal_id)
        await self.store(
            w,
            ctx,
            [
                ("user", [{"type": "text", "text": text}]),
                ("assistant", [*said, use]),
                ("user", [result]),
            ],
        )
        self.sup.finish(w, "answered")

    # ── brain → device ────────────────────────────────────────────────────────────────────

    async def delta(self, w: Watch, text: str, tone: str | None = None) -> None:
        self.sup.mark(w, "first_delta")
        await live.send(
            self.rt,
            w.device_id,
            "reply.delta",
            {"signal_id": w.signal_id, "text": text, "tone": tone, "speak": True, "final": False},
        )

    async def end(self, w: Watch) -> None:
        await live.send(
            self.rt,
            w.device_id,
            "reply.delta",
            {"signal_id": w.signal_id, "text": "", "tone": None, "speak": False, "final": True},
        )

    async def cue(self, w: Watch, kind: Cue) -> None:
        await live.send(self.rt, w.device_id, "reply.cue", {"signal_id": w.signal_id, "kind": kind})

    async def store(
        self, w: Watch, ctx: Context, turn: list[tuple[str, list[dict[str, Any]]]]
    ) -> None:
        try:
            await context.store_turn(
                self.rt,
                w.user_id,
                w.device_id,
                ctx,
                signal_id=w.signal_id,
                tier=w.tier,
                messages=turn,
            )
        except Exception:
            logger.error("turn not stored", exc_info=True)

    async def fail(self, w: Watch, moment: persona.Moment, *, stage: str, error: str) -> None:
        """§19.2 step 8: spoken and visible, with a reason. Never silence."""
        text = await persona.phrase(self.rt.redis, w.user_id, moment)
        await self.delta(w, text, tone="serious")
        self.sup.finish(w, "failed_explained")
        await self.end(w)
        await self.cue(w, "error")
        await self.sup.incident(
            w, stage=stage, error=error, remedy="explain", outcome="failed_explained"
        )

    async def explain(self, w: Watch, reason: str) -> None:
        text = await persona.phrase(self.rt.redis, w.user_id, "stuck")
        await self.delta(w, text, tone="serious")
        await self.end(w)
        await self.cue(w, "error")

    async def call_device(self, w: Watch, spec: ToolSpec, raw: dict[str, Any]) -> tuple[bool, str]:
        """Runs a device tool on the origin device; (ok, content for the model)."""
        try:
            inp = spec.validate(raw)
        except ValidationError as exc:
            first = exc.errors()[0]
            return False, f"Invalid input for {spec.name}: {first['loc']} {first['msg']}"
        call_id = uuid.uuid4().hex
        fut: asyncio.Future[ToolResult] = asyncio.get_running_loop().create_future()
        self.calls[call_id] = (w.user_id, fut)
        self.sup.mark(w, f"tool:{spec.name}")
        try:
            await live.send(
                self.rt,
                w.device_id,
                "tool.call",
                {
                    "call_id": call_id,
                    "job_id": None,
                    "signal_id": w.signal_id,
                    "tool": spec.name,
                    "input": inp,
                    "timeout_s": spec.timeout_s,
                    "risk": spec.risk.value,
                },
            )
            res = await within(self.rt.clock, fut, spec.timeout_s)
        except TimeoutError:
            await live.send(self.rt, w.device_id, "tool.cancel", {"call_id": call_id})
            await self.sup.incident(
                w,
                stage="tool",
                engine=spec.name,
                error="timeout",
                remedy="replan",
                outcome="failed_explained",
            )
            return False, f"The device didn't finish {spec.name} within {spec.timeout_s:.0f}s."
        finally:
            self.calls.pop(call_id, None)
        self.sup.mark(w, f"tool_done:{spec.name}")
        if res.ok:
            return True, reflex.tool_content(res.output if res.output is not None else "ok")
        return False, res.error.message if res.error else f"{spec.name} failed."
