"""Jobs (REDESIGN §6.1, §6.4): one delegated task = one asyncio task running the agent loop,
persisted at every step and pushed to every device as `job.update`. Jobs can be cancelled,
steered, and asked about; approvals and questions block a job until a device answers (the first
answer wins) or they expire. The supervisor watches each job: a deadline, and an estimate check."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import update

from app.agent import persona
from app.agent.context import Context
from app.artifacts import store as artifacts
from app.core.clock import within
from app.db.base import uuid7
from app.db.models import Approval, JobStep
from app.db.models import Job as JobRow
from app.gateway import push
from app.supervisor.watch import Watch
from app.tools import permissions
from app.tools.permissions import Rule
from app.tools.spec import ToolSpec

if TYPE_CHECKING:
    from app.agent.voice import Voice
    from app.capabilities.hooks import Outcome

logger = logging.getLogger(__name__)

JOB_DEADLINE_S = 900.0
APPROVAL_TIMEOUT_S = 120.0
ASK_TIMEOUT_S = 300.0
ASK_ANSWER_WINDOW_S = 60.0  # a spoken line this soon after the question answers it (tier 1)
MAX_ACTIVE = 3  # per user (§6.2); more wait their turn
SPOKEN_SENTENCES = 3  # PERSONA §3: the wrap-up, out loud
_RETRY = re.compile(r"\b(?:that'?s (?:wrong|not right)|try again|you got it wrong)\b", re.I)
_PATH = re.compile(r"(?:[A-Za-z]:[\\/])?(?:[\w.\-]+[\\/])+[\w.\-*]*")


def spoken(text: str) -> str:
    """Paths read badly out loud: 'delete C:/Users/a/Downloads/*' → 'delete everything in
    Downloads'; other paths keep their last part."""

    def short(m: re.Match[str]) -> str:
        parts = [p for p in re.split(r"[\\/]", m.group(0).strip()) if p and not p.endswith(":")]
        if len(parts) >= 2 and parts[-1] == "*":
            return f"everything in {parts[-2]}"
        return parts[-1] if parts else m.group(0)

    return _PATH.sub(short, text)


def _secs(s: float) -> str:
    if s < 60:
        return f"{max(10, round(s / 5) * 5)} seconds"
    m = round(s / 60)
    return "a minute" if m <= 1 else f"{m} minutes"


@dataclass
class Job:
    id: uuid.UUID
    user_id: uuid.UUID
    device_id: uuid.UUID  # origin: where the user asked, where the wrap-up is spoken
    signal_id: str
    title: str
    task: str
    request: str  # the user's own words (the reviewer checks calls against them)
    note: str  # volatile context for the first message: time, device
    ctx: Context
    rules: list[Rule] = field(default_factory=list)
    status: str = "queued"
    todo: list[dict[str, Any]] = field(default_factory=list)
    eta_s: int | None = None
    eta_t0: float = 0.0
    steer: list[str] = field(default_factory=list)  # not yet seen by the model
    said: list[str] = field(default_factory=list)  # everything the user added (grounding)
    exclude: set[str] = field(default_factory=set)  # chain entries escalated past
    grants: list[Rule] = field(default_factory=list)  # from an approved plan, this job only
    current: str = ""  # the step running now, spoken form
    provider: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    watch: Watch | None = None
    runner: asyncio.Task[None] | None = None


class Jobs:
    def __init__(self, voice: Voice) -> None:
        self.voice = voice
        self.rt = voice.rt
        # ponytail: in-process, like Voice.calls: a single brain process until R7. Approval
        # decisions are atomic in Postgres already; the futures move to Redis pub/sub with it.
        self.active: dict[uuid.UUID, Job] = {}
        self.slots: dict[uuid.UUID, asyncio.Semaphore] = {}
        self.approvals: dict[str, tuple[uuid.UUID, asyncio.Future[str], Job]] = {}
        self.asks: dict[str, tuple[uuid.UUID, asyncio.Future[str], Job, float]] = {}

    # ── lifecycle ─────────────────────────────────────────────────────────────────────────

    async def start(self, w: Watch, ctx: Context, task: str, request: str, note: str) -> Job:
        rt = self.rt
        title = task.strip().splitlines()[0][:80] if task.strip() else "Job"
        job = Job(
            uuid7(),
            w.user_id,
            w.device_id,
            w.signal_id,
            title,
            task,
            request,
            note,
            ctx,
            rules=await permissions.load(rt, w.user_id),
        )
        async with rt.db() as db:
            db.add(
                JobRow(
                    id=job.id,
                    user_id=job.user_id,
                    thread_id=ctx.thread_id,
                    device_id=job.device_id,
                    signal_id=job.signal_id,
                    title=title,
                    status="queued",
                )
            )
            await db.commit()
        job.watch = self.voice.sup.track(
            Watch(
                job.user_id,
                job.device_id,
                job.signal_id,
                rt.clock.monotonic(),
                deadline_s=JOB_DEADLINE_S,
                tier=3,
                name=f"job:{job.id}",
                on_expire=lambda _w, _r: self._expired(job),
                check=lambda: self._check_eta(job),
            )
        )
        self.active[job.id] = job
        job.runner = self.voice._spawn(self._run(job))
        job.watch.task = job.runner
        await self.push(job)
        return job

    async def _run(self, job: Job) -> None:
        from app.agent import loop  # the loop needs Jobs; imported late to avoid a cycle

        slots = self.slots.setdefault(job.user_id, asyncio.Semaphore(MAX_ACTIVE))
        try:
            async with slots:
                await self._set(job, "running")
                state, text = await loop.run(self, job)
            await self._finish(job, state, text)
        except asyncio.CancelledError:
            raise  # cancel() and the supervisor do the bookkeeping
        except Exception:
            logger.error("job crashed", exc_info=True)
            await self._finish(
                job, "failed", await persona.phrase(self.rt.redis, job.user_id, "failure")
            )

    async def _finish(self, job: Job, state: str, text: str) -> None:
        if job.id not in self.active:
            return
        rt, w = self.rt, job.watch
        assert w is not None
        failed = state != "done"
        said: list[tuple[str | None, str]] = []
        for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
            tag, body = persona.split_tone(sentence)
            if body := persona.lint(body):
                said.append((tag, body))
        said = said or [(None, await persona.phrase(rt.redis, job.user_id, "done"))]
        full = " ".join(body for _, body in said)
        artifact_id = None
        if len(said) > SPOKEN_SENTENCES:  # PS3: the gist out loud, the rest on screen
            art = await artifacts.save_text(
                rt, job.user_id, job.ctx.thread_id, job.id, job.title, full
            )
            artifact_id = str(art.id)
        for tag, body in said[:SPOKEN_SENTENCES]:
            await self.voice.delta(w, body, tone=tag or ("serious" if failed else None))
        await self.voice.end(w)
        if failed:
            await self.voice.cue(w, "error")
        await self.voice.store(w, job.ctx, [("assistant", [{"type": "text", "text": full}])])
        job.status = "failed" if failed else "done"
        await self._save(
            job,
            status=job.status,
            summary=full,
            todo=job.todo,
            provider_used=job.provider,
            usage=job.usage,
            thread_id=job.ctx.thread_id,
            finished_at=rt.clock.now(),
        )
        await self.push(job, summary=full, artifact_id=artifact_id)
        self.voice.sup.finish(w, "failed_explained" if failed else "answered")
        self.active.pop(job.id, None)

    async def cancel(self, job: Job) -> None:
        """Stops the job now: its task is cancelled (in-flight device calls get tool.cancel),
        waiting approvals and questions expire, every device hears about it."""
        if job.id not in self.active or job.status == "cancelled":
            return
        job.status = "cancelled"
        waiting = [k for k, (_, _, j) in self.approvals.items() if j is job]
        asked = [k for k, (_, _, j, _) in self.asks.items() if j is job]
        runner = job.runner
        if runner is not None and not runner.done() and runner is not asyncio.current_task():
            runner.cancel()
            await asyncio.wait({runner})
        for approval_id in waiting:
            await self.resolve(job.user_id, approval_id, "expired", None)
        for ask_id in asked:
            await self._event(job.user_id, "ask.resolved", {"ask_id": ask_id, "answer": None})
        await self._save(job, status="cancelled", finished_at=self.rt.clock.now())
        await self.push(job)
        if job.watch is not None:
            self.voice.sup.finish(job.watch, "cancelled")
        self.active.pop(job.id, None)

    async def _expired(self, job: Job) -> None:
        """The supervisor's deadline passed (§19.2 step 8): said, shown, recorded."""
        if job.id not in self.active:
            return
        job.status = "failed"
        assert job.watch is not None
        text = await persona.phrase(self.rt.redis, job.user_id, "stuck")
        await self.say(job, text, "serious")
        await self.voice.cue(job.watch, "error")
        await self._save(job, status="failed", summary=text, finished_at=self.rt.clock.now())
        await self.push(job, summary=text)
        self.active.pop(job.id, None)

    async def fail_stale(self) -> None:
        """Brain start: jobs that were running when it stopped end explained, never dropped."""
        async with self.rt.db() as db:
            rows = (
                await db.execute(
                    update(JobRow)
                    .where(JobRow.status.in_(("queued", "running", "waiting")))
                    .values(
                        status="failed",
                        summary="I restarted in the middle of this one. Ask me again?",
                        finished_at=self.rt.clock.now(),
                    )
                    .returning(JobRow.id, JobRow.user_id, JobRow.title)
                )
            ).all()
            events = [
                await push.record(
                    self.rt,
                    db,
                    user_id,
                    "job.update",
                    {"job_id": str(job_id), "status": "failed", "title": title, "todo": []},
                )
                for job_id, user_id, title in rows
            ]
            await db.commit()
        for ev in events:
            await push.emit(self.rt, ev)
        if rows:
            logger.warning("failed %d jobs left running by a restart", len(rows))

    # ── what the user can do while it runs ────────────────────────────────────────────────

    def mine(self, user_id: uuid.UUID) -> list[Job]:
        """Active jobs, newest first."""
        return [j for j in reversed(self.active.values()) if j.user_id == user_id]

    def find(self, user_id: uuid.UUID, hint: str | None = None) -> Job | None:
        jobs = self.mine(user_id)
        if hint:
            words = set(hint.lower().split())
            named = [j for j in jobs if words & set(j.title.lower().split())]
            jobs = named or jobs
        return jobs[0] if jobs else None

    def steer(self, job: Job, text: str) -> None:
        """Picked up before the model's next turn (§6.4). "That's wrong, try again" also moves
        the job to the next chain entry (§5.2 escalation)."""
        job.steer.append(text)
        job.said.append(text)
        if _RETRY.search(text) and job.provider:
            job.exclude.add(job.provider)

    def status_line(self, job: Job) -> str:
        """RA3: from job state, no LLM."""
        if job.status == "waiting":
            return "I'm waiting on you for that one. Check the card on screen."
        if job.status == "queued":
            return "It's queued. I'll start as soon as the others finish."
        now = f" Working on: {job.current}." if job.current else ""
        if job.todo:
            done = sum(1 for t in job.todo if t.get("status") == "done")
            return f"{done} of {len(job.todo)} done.{now}"
        return f"Still on it.{now}"

    async def _check_eta(self, job: Job) -> None:
        """S7: twice over its estimate → a progress note with a new one."""
        if job.status != "running" or not job.eta_s or job.watch is None:
            return
        now = self.rt.clock.monotonic()
        if now - job.eta_t0 <= 2 * job.eta_s:
            return
        done = sum(1 for t in job.todo if t.get("status") == "done")
        left = len(job.todo) - done
        elapsed = now - job.watch.t0
        guess = elapsed / done * left if done and left else max(job.eta_s, elapsed)
        job.eta_s, job.eta_t0 = max(10, round(guess)), now
        note = f"This is taking longer than I thought. About {_secs(job.eta_s)} more."
        await self.say(job, note)
        await self.push(job, note=note)

    # ── approvals and questions ───────────────────────────────────────────────────────────

    async def approve(
        self,
        job: Job,
        *,
        tool: str,
        summary: str,
        preview: dict[str, Any],
        risk: str,
        options: tuple[str, ...] = ("allow", "always", "deny"),
    ) -> str:
        """Asks every device (§7.2) and says it on the origin; blocks the job until the first
        answer or the timeout. → allow | always | deny | expired."""
        rt = self.rt
        approval_id = uuid7()
        async with rt.db() as db:
            db.add(
                Approval(
                    id=approval_id,
                    user_id=job.user_id,
                    job_id=job.id,
                    tool=tool,
                    summary=summary[:500],
                    risk=risk,
                    inputs_preview=preview,
                )
            )
            await db.commit()
        fut: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        key = str(approval_id)
        self.approvals[key] = (job.user_id, fut, job)
        await self._set(job, "waiting")
        await self._event(
            job.user_id,
            "approval.request",
            {
                "approval_id": key,
                "job_id": str(job.id),
                "tool": tool,
                "summary": summary,
                "inputs_preview": preview,
                "risk": risk,
                "options": list(options),
            },
        )
        await self.say(job, f"Heads up, this will {spoken(summary)}. Go ahead?", "serious")
        try:
            decision = await within(rt.clock, fut, APPROVAL_TIMEOUT_S)
        except TimeoutError:
            await self.resolve(job.user_id, key, "expired", None)
            decision = "expired"
        finally:
            self.approvals.pop(key, None)
        await self._set(job, "running")
        return decision

    async def resolve(
        self, user_id: uuid.UUID, approval_id: str, decision: str, device_id: uuid.UUID | None
    ) -> bool:
        """First answer wins, across devices and processes (the row only updates once)."""
        try:
            aid = uuid.UUID(approval_id)
        except ValueError:
            return False
        async with self.rt.db() as db:
            won = (
                await db.execute(
                    update(Approval)
                    .where(
                        Approval.id == aid,
                        Approval.user_id == user_id,
                        Approval.decision.is_(None),
                    )
                    .values(
                        decision=decision,
                        decided_by_device=device_id,
                        decided_at=self.rt.clock.now(),
                    )
                    .returning(Approval.id)
                )
            ).first()
            await db.commit()
        if won is None:
            return False
        await self._event(
            user_id,
            "approval.resolved",
            {
                "approval_id": approval_id,
                "decision": decision,
                "by_device": str(device_id) if device_id else None,
            },
        )
        entry = self.approvals.get(approval_id)
        if entry is not None and not entry[1].done():
            entry[1].set_result(decision)
        return True

    def pending_approval(self, user_id: uuid.UUID) -> str | None:
        mine = [k for k, (u, f, _) in self.approvals.items() if u == user_id and not f.done()]
        return mine[-1] if mine else None

    async def ask(self, job: Job, question: str, options: list[str]) -> str | None:
        """ask_user (§5.2): a spoken question + a UI choice; None if nobody answers in time."""
        ask_id = uuid.uuid4().hex
        fut: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self.asks[ask_id] = (job.user_id, fut, job, self.rt.clock.monotonic())
        await self._set(job, "waiting")
        await self._event(
            job.user_id,
            "ask.request",
            {"ask_id": ask_id, "job_id": str(job.id), "question": question, "options": options},
        )
        await self.say(job, question)
        try:
            answer: str | None = await within(self.rt.clock, fut, ASK_TIMEOUT_S)
        except TimeoutError:
            answer = None
        finally:
            self.asks.pop(ask_id, None)
        await self._event(job.user_id, "ask.resolved", {"ask_id": ask_id, "answer": answer})
        if answer:
            job.said.append(answer)
        await self._set(job, "running")
        return answer

    def pending_ask(self, user_id: uuid.UUID, *, spoken_window: bool = False) -> str | None:
        now = self.rt.clock.monotonic()
        mine = [
            k
            for k, (u, f, _, t) in self.asks.items()
            if u == user_id
            and not f.done()
            and (not spoken_window or now - t <= ASK_ANSWER_WINDOW_S)
        ]
        return mine[-1] if mine else None

    def answer(self, user_id: uuid.UUID, ask_id: str, text: str) -> bool:
        entry = self.asks.get(ask_id)
        if entry is None or entry[0] != user_id or entry[1].done():
            return False
        entry[1].set_result(text)
        return True

    # ── steps, notes, pushes, speech ──────────────────────────────────────────────────────

    async def step_start(
        self, job: Job, spec: ToolSpec, inp: dict[str, Any], device_id: uuid.UUID | None
    ) -> uuid.UUID:
        step_id = uuid7()
        job.current = spoken(spec.describe(inp)) if spec.confirm else spec.name.replace("_", " ")
        async with self.rt.db() as db:
            db.add(
                JobStep(
                    id=step_id,
                    job_id=job.id,
                    user_id=job.user_id,
                    tool=spec.name,
                    input=inp,
                    device_id=device_id,
                    started_at=self.rt.clock.now(),
                )
            )
            await db.commit()
        await self.push(job, step=self._step(step_id, spec, inp, device_id, "running"))
        return step_id

    async def step_end(
        self,
        job: Job,
        step_id: uuid.UUID,
        spec: ToolSpec,
        inp: dict[str, Any],
        device_id: uuid.UUID | None,
        out: Outcome,
    ) -> None:
        status = "ok" if out.ok else "denied" if out.decision in ("deny", "expired") else "error"
        async with self.rt.db() as db:
            await db.execute(
                update(JobStep)
                .where(JobStep.id == step_id, JobStep.user_id == job.user_id)
                .values(
                    status=status,
                    output=out.content[:2000],
                    error=None if out.ok else out.content[:300],
                    finished_at=self.rt.clock.now(),
                )
            )
            await db.commit()
        job.current = ""
        await self.push(job, step=self._step(step_id, spec, inp, device_id, status))

    @staticmethod
    def _step(
        step_id: uuid.UUID,
        spec: ToolSpec,
        inp: dict[str, Any],
        device_id: uuid.UUID | None,
        status: str,
    ) -> dict[str, Any]:
        return {
            "id": str(step_id),
            "tool": spec.name,
            "summary": spec.describe(inp) if spec.confirm else spec.name.replace("_", " "),
            "input": inp,
            "status": status,
            "device_id": str(device_id) if device_id else None,
        }

    async def save_todo(self, job: Job) -> None:
        await self._save(job, todo=job.todo, eta_s=job.eta_s)
        await self.push(job)

    async def note(self, job: Job, text: str) -> None:
        """What the agent says between tool calls: on screen, not spoken."""
        await self.push(job, note=persona.lint(text)[:300])

    async def say(self, job: Job, text: str, tone: str | None = None) -> None:
        assert job.watch is not None
        await self.voice.delta(job.watch, text, tone=tone)
        await self.voice.end(job.watch)

    async def _set(self, job: Job, status: str) -> None:
        if job.status == "cancelled":
            return
        job.status = status
        await self._save(job, status=status)
        await self.push(job)

    async def _save(self, job: Job, **values: Any) -> None:
        try:
            async with self.rt.db() as db:
                await db.execute(
                    update(JobRow)
                    .where(JobRow.id == job.id, JobRow.user_id == job.user_id)
                    .values(**values)
                )
                await db.commit()
        except Exception:
            logger.warning("job row not saved", exc_info=True)

    async def push(self, job: Job, **extra: Any) -> None:
        payload = {
            "job_id": str(job.id),
            "status": job.status,
            "title": job.title,
            "todo": job.todo,
            "eta_s": job.eta_s,
            **{k: v for k, v in extra.items() if v is not None},
        }
        await self._event(job.user_id, "job.update", payload)

    async def _event(self, user_id: uuid.UUID, type_: str, payload: dict[str, Any]) -> None:
        """Synced to every device of the user (API.md §3.2)."""
        try:
            async with self.rt.db() as db:
                ev = await push.record(self.rt, db, user_id, type_, payload)
                await db.commit()
            await push.emit(self.rt, ev)
        except Exception:
            logger.warning("event not pushed", extra={"event": type_}, exc_info=True)


__all__ = ["Job", "Jobs", "spoken"]
