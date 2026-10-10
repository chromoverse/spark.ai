"""The voice loop in the brain (REDESIGN §4.1, §26.4 A to D): signal in → tier 1 or reflex →
reply.delta / reply.cue / tool.call out; multi-step work becomes a job (§6.1). Every signal gets a
supervisor watch and ends answered, cancelled, or explained (§19.2)."""

from __future__ import annotations

import asyncio
import json
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
    ApprovalResponse,
    AskResponse,
    EngineIncident,
    SignalFinal,
    SignalHandledLocally,
    SignalInterrupt,
    SignalPartial,
    SignalTrace,
    ToolResult,
)
from app.jobs.runtime import Jobs
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
        self.calls: dict[str, tuple[uuid.UUID, uuid.UUID, asyncio.Future[ToolResult]]] = {}
        self.prefetch: dict[tuple[uuid.UUID, str], tuple[float, asyncio.Task[Context]]] = {}
        self.tasks: set[asyncio.Task[Any]] = set()
        self.jobs = Jobs(self)

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
        intent = self._tier1_intent(p, msg.text)
        w.tier = 1 if intent else 2
        if intent is not None:
            w.task = self._spawn(self._tier1(p, w, msg, intent))
        else:
            w.task = self._spawn(self._reflex(p, w, msg.text, msg.utc_offset_min, None))
            self._spawn(self.sup.heard_cue(w, lambda: self.cue(w, "heard")))
        self.sup.mark(w, "ack")
        return {"signal_id": msg.signal_id, "tier": w.tier}

    def _tier1_intent(self, p: Principal, text: str) -> tier1.Intent | None:
        """Tier 1 only when sure: status needs a running job, yes/no a pending approval. Any
        other line soon after a job's spoken question answers it (§27)."""
        intent = tier1.classify(text)
        if intent is not None and intent.kind == "status" and not self.jobs.mine(p.user_id):
            intent = None
        if intent is not None and intent.kind == "confirm":
            approval = self.jobs.pending_approval(p.user_id)
            intent = tier1.Intent("confirm", intent.value, approval) if approval else None
        if intent is None and (ask := self.jobs.pending_ask(p.user_id, spoken_window=True)):
            intent = tier1.Intent("answer", text, ask)
        return intent

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
        if msg.scope == "all" and (job := self.jobs.find(p.user_id)) is not None:
            await self.jobs.cancel(job)  # a spoken "stop" stops the work too (§6.4)
        if w is None:
            return {"cancelled": None}
        await self.sup.cancel(w)
        return {"cancelled": w.signal_id}

    async def tool_result(self, p: Principal, msg: ToolResult) -> dict[str, Any]:
        entry = self.calls.get(msg.call_id)
        if entry is None or entry[0] != p.user_id or entry[1] != p.device_id:
            return {"accepted": False}  # late, unknown, or another user's / device's call
        if not entry[2].done():
            entry[2].set_result(msg)
        return {"accepted": True}

    async def approval_response(self, p: Principal, msg: ApprovalResponse) -> dict[str, Any]:
        won = await self.jobs.resolve(p.user_id, msg.approval_id, msg.decision, p.device_id)
        return {"accepted": won}

    async def ask_response(self, p: Principal, msg: AskResponse) -> dict[str, Any]:
        return {"accepted": self.jobs.answer(p.user_id, msg.ask_id, msg.answer)}

    def device_gone(self, device_id: uuid.UUID) -> None:
        """Its socket dropped: calls waiting on it fail now instead of at their timeout (S3)."""
        for _, dev, fut in list(self.calls.values()):
            if dev == device_id and not fut.done():
                fut.set_exception(DeviceGone())

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
        jobs = self.jobs
        if intent.kind == "stop":
            for other in [o for o in self.sup.watches.values() if o.user_id == p.user_id]:
                if other is not w and not other.name:
                    await self.sup.cancel(other)
            if (job := jobs.find(p.user_id)) is not None:
                await jobs.cancel(job)
            reply = await persona.phrase(self.rt.redis, p.user_id, "ack")
        elif intent.kind == "status":
            job = jobs.find(p.user_id)
            reply = jobs.status_line(job) if job else "Nothing's running right now."
        elif intent.kind == "confirm":
            await jobs.resolve(p.user_id, intent.ref or "", intent.value or "deny", p.device_id)
            reply = {
                "allow": await persona.phrase(self.rt.redis, p.user_id, "ack"),
                "always": "Got it. I won't ask about that one again.",
            }.get(intent.value or "", "Okay, I won't.")
        elif intent.kind == "answer":
            jobs.answer(p.user_id, intent.ref or "", msg.text)
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
        """Validates, then runs a device tool on the origin device; (ok, content for the model)."""
        try:
            inp = spec.validate(raw)
        except ValidationError as exc:
            first = exc.errors()[0]
            return False, f"Invalid input for {spec.name}: {first['loc']} {first['msg']}"
        ok, content = await self.device_call(w, spec, inp)
        return ok, content[:2000]  # the reflex keeps tool results short

    async def device_call(
        self,
        w: Watch,
        spec: ToolSpec,
        inp: dict[str, Any],
        *,
        device_id: uuid.UUID | None = None,
        job_id: uuid.UUID | None = None,
    ) -> tuple[bool, str]:
        """Sends an already-checked call to a device (the origin by default) and waits for its
        tool.result within the tool's timeout (API.md §3.3)."""
        target = device_id or w.device_id
        call_id = uuid.uuid4().hex
        fut: asyncio.Future[ToolResult] = asyncio.get_running_loop().create_future()
        self.calls[call_id] = (w.user_id, target, fut)
        self.sup.mark(w, f"tool:{spec.name}")
        try:
            await live.send(
                self.rt,
                target,
                "tool.call",
                {
                    "call_id": call_id,
                    "job_id": str(job_id) if job_id else None,
                    "signal_id": w.signal_id,
                    "tool": spec.name,
                    "input": inp,
                    "timeout_s": spec.timeout_s,
                    "risk": spec.risk.value,
                },
            )
            res = await within(self.rt.clock, fut, spec.timeout_s)
        except TimeoutError:
            await live.send(self.rt, target, "tool.cancel", {"call_id": call_id})
            await self.sup.incident(
                w,
                stage="tool",
                engine=spec.name,
                error="timeout",
                remedy="replan",
                outcome="failed_explained",
            )
            return False, f"The device didn't finish {spec.name} within {spec.timeout_s:.0f}s."
        except DeviceGone:
            await self.sup.incident(
                w,
                stage="tool",
                engine=spec.name,
                error="device offline",
                remedy="replan",
                outcome="failed_explained",
            )
            return False, DeviceGone.message
        except asyncio.CancelledError:
            await live.send(self.rt, target, "tool.cancel", {"call_id": call_id})
            raise
        finally:
            self.calls.pop(call_id, None)
        self.sup.mark(w, f"tool_done:{spec.name}")
        if not res.ok:
            return False, res.error.message if res.error else f"{spec.name} failed."
        try:
            output = spec.check_output(res.output)
        except ValidationError:
            await self.sup.incident(
                w,
                stage="tool",
                engine=spec.name,
                error="output didn't match its schema",
                remedy="replan",
                outcome="failed_explained",
            )
            return False, f"The device sent back something unexpected for {spec.name}."
        if output is None or isinstance(output, str):
            return True, output or "ok"
        return True, json.dumps(output, default=str)


class DeviceGone(Exception):
    message = "That device went offline before it finished."
