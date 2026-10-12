"""Reflex (REDESIGN §5.1, §4.4): one streamed call on the reflex chain. Text is spoken sentence by
sentence while quick tools run on the origin device in parallel; then a done cue, a short "Done.",
or a follow-up turn that explains a failure. Multi-step work goes to `delegate`, which starts a
job (§6.1). While jobs run, the reflex is the signal router for them (§6.4): steer or cancel."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from app.agent import persona
from app.agent.context import Context
from app.agent.speech import Splitter
from app.llm.types import ChainExhausted, Done, Restart, TextDelta, ToolDef, ToolUse
from app.llm.types import Message as LlmMessage
from app.memory import store as memory
from app.memory.tools import FORGET, REMEMBER
from app.supervisor.watch import State, Watch
from app.tools.device_specs import QUICK_TOOLS
from app.tools.spec import Risk, ToolSpec

if TYPE_CHECKING:
    from app.agent.voice import Voice


class Delegate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: str = Field(max_length=2000, description="The full task, in the user's terms")
    ack: str = Field(max_length=120, description="Short spoken acknowledgement, e.g. 'On it.'")


class JobSteer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(max_length=500, description="What the user wants changed, in their words")
    job: str | None = Field(default=None, max_length=80, description="Job title if several run")


class JobCancel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job: str | None = Field(default=None, max_length=80, description="Job title if several run")


DELEGATE = ToolSpec(
    "delegate",
    "Hands work you can't do in one reply (files, email, calendar, current web info, live "
    "data, several steps, risky actions) to the agent. Not for facts you know. Say the ack "
    "out loud first.",
    Delegate,
    "brain",
    Risk.READ,
)
JOB_STEER = ToolSpec(
    "job_steer",
    "Passes the user's change or addition to the running job ('use the D drive instead').",
    JobSteer,
    "brain",
    Risk.READ,
)
JOB_CANCEL = ToolSpec(
    "job_cancel",
    "Stops the running job when the user wants it stopped.",
    JobCancel,
    "brain",
    Risk.READ,
)
TOOLS: tuple[ToolSpec, ...] = (*QUICK_TOOLS, DELEGATE, REMEMBER, FORGET)
TOOL_DEFS = [t.to_def() for t in TOOLS]
JOB_TOOL_DEFS = [JOB_STEER.to_def(), JOB_CANCEL.to_def()]


# Offered only when the line talks about remembering: with remember/forget always listed, the
# free models delegated file work less ("I can't delete files"), 2026-10-11 reflex eval A/B.
_MEMORY_TALK = re.compile(r"\b(remember|forget|forgot|memori[sz]e|memory)\b", re.I)


def tool_defs(
    capabilities: frozenset[str],
    hidden: frozenset[str] = frozenset(),
    *,
    jobs: bool = False,
    with_device: bool = False,
    said: str = "",
) -> list[ToolDef]:
    """Only tools some device of the user can run (device.hello capabilities) and no bare-denied
    ones, in catalog order so the prompt prefix stays cacheable. With several devices each device
    tool takes an optional `device` (§26.3). delegate is always offered; job_steer / job_cancel
    only while a job runs; remember / forget only when the line is about remembering."""
    memory = bool(_MEMORY_TALK.search(said))
    defs = [
        t.to_def(with_device=True) if with_device else d
        for t, d in zip(TOOLS, TOOL_DEFS, strict=True)
        if t.requires <= capabilities
        and t.name not in hidden
        and (memory or t.name not in MEMORY_TOOLS)
    ]
    return [*defs, *JOB_TOOL_DEFS] if jobs else defs


BY_NAME = {t.name: t for t in (*TOOLS, JOB_STEER, JOB_CANCEL)}
MEMORY_TOOLS = {REMEMBER.name: REMEMBER, FORGET.name: FORGET}

SYSTEM = (
    persona.PERSONA_BLOCK
    + """

This turn: the user just spoke to you. Answer fast, in 1 to 3 short sentences unless they ask \
for more.
- For volume, media, opening apps, or brightness, call the device tool. In the same reply, say a \
short phrase of what you're doing first ("Turning it up."). Don't wait for the result.
- Most of what people ask, just answer from what you know, no tools: facts (science, \
history, places, numbers), how-to tips, recommendations, jokes, chat, opinions, advice. The time \
and date are in the context note.
- If none of your tools could do it (drive a car, read minds, predict the future, phone \
someone, see their bank account, do their taxes, set a reminder), never delegate it: say lightly \
that you can't, then offer the closest thing you can do.
- Call delegate only when the answer needs what you can't know or do in one reply: files, \
email, the calendar, a web search for something current, live data (weather, news, prices, \
battery), several steps, or anything risky. Give it the task and a short ack.
- If what you heard is a fragment or makes no sense (a speech-to-text slip, "okay okay", half \
a sentence), say in a few words that you didn't catch it. Never delegate it, never guess.
- If the context note lists a running job: when the user changes or adds to it, call \
job_steer; when they want it stopped, call job_cancel; say a few words either way.
- If they name another of their devices ("on my phone"), set device on the tool.
- You remember things about the user (below, and "remembered" in the context note). Use them \
when they help, never recite them. Say the names of people you know about, not "your sister". \
When \
they ask you to remember or forget something about themselves, call remember or forget.
- The (context: ...) note at the end of the user's message is for you. Use it, never read it out.
- Never claim you did something no tool did.
- Never include internal or system XML tags in your reply."""
)

FAST_DONE_S = 1.5  # §4.4: faster quick actions get a chime, slower ones a spoken "Done."


def system(ctx: Context) -> str:
    """Static first, then the user's profile: stable per user, so the prefix stays cached (§21)."""
    if not ctx.profile:
        return SYSTEM
    return f"{SYSTEM}\n\nWhat you know about the user: {memory.render(ctx.profile)}"


def volatile_context(
    ctx: Context,
    utc_offset_min: int | None,
    now_utc: Any,
    jobs: list[str] | None = None,
    origin: Any = None,
    remembered: list[memory.Found] | None = None,
) -> str:
    tz = timezone(timedelta(minutes=utc_offset_min or 0))
    local = now_utc.astimezone(tz)
    when = local.strftime("%A %d %B %Y, %I:%M %p").replace(" 0", " ")
    parts = [
        f"it's {when} local time" if utc_offset_min is not None else f"it's {when} UTC",
        f"device: {ctx.device_name}",
    ]
    if ctx.verbosity == "brief":
        parts.append("keep it extra short")
    if ctx.address_as:
        parts.append(f"you may call the user {ctx.address_as} now and then")
    if jobs:
        parts.append("running job: " + " | ".join(jobs))
    if ctx.multi and origin is not None:
        parts.append("devices: " + ctx.devices_note(origin))
    if remembered:
        parts.append("remembered: " + memory.render(remembered))
    return "(context: " + "; ".join(parts) + ")"


@dataclass
class Speaker:
    """Turns stream text into reply.delta events: split, tone tag, lint, send."""

    voice: Voice
    w: Watch
    splitter: Splitter = field(default_factory=Splitter)
    spoken: list[str] = field(default_factory=list)

    async def feed(self, text: str) -> None:
        for chunk in self.splitter.feed(text):
            await self.say(chunk)

    async def flush(self) -> None:
        for chunk in self.splitter.flush():
            await self.say(chunk)

    async def say(self, chunk: str, tone: str | None = None) -> None:
        tag, body = persona.split_tone(chunk)
        body = persona.lint(body)
        if not body:
            return
        await self.voice.delta(self.w, body, tone=tag or tone)
        self.spoken.append(body)

    def text(self) -> str:
        return " ".join(self.spoken)


async def run(
    voice: Voice,
    w: Watch,
    ctx: Context,
    user_text: str,
    *,
    utc_offset_min: int | None,
    after: list[LlmMessage] | None = None,
) -> None:
    """One reflex turn for signal `w`. `after` continues a turn that already happened (a tier-0
    action that failed): the model then explains instead of calling tools."""
    rt = voice.rt
    running = voice.jobs.mine(w.user_id)
    lines = [f"{j.title} ({voice.jobs.status_line(j)})" for j in running]
    note = volatile_context(
        ctx, utc_offset_min, rt.clock.now(), lines, w.device_id, remembered=ctx.memories
    )
    user_msg: LlmMessage = {
        "role": "user",
        "content": [{"type": "text", "text": f"{user_text}\n\n{note}"}],
    }
    messages = [*ctx.history, user_msg, *(after or [])]
    speaker = Speaker(voice, w)
    blocks: list[dict[str, Any]] = []
    calls: list[tuple[ToolUse, asyncio.Task[tuple[bool, str]]]] = []
    delegated: Delegate | None = None
    routed: list[tuple[ToolUse, str]] = []  # job_steer / job_cancel: run in the brain at once
    tools_t0 = 0.0

    stream = rt.llm.stream(
        "reflex",
        system=system(ctx),
        messages=messages,
        tools=()
        if after
        else tool_defs(
            ctx.all_capabilities,
            ctx.hidden,
            jobs=bool(running),
            with_device=ctx.multi,
            said=user_text,
        ),
        allow_training=ctx.allow_training,
    )
    try:
        async for ev in stream:
            if isinstance(ev, TextDelta):
                voice.sup.mark(w, "ttft")
                await speaker.feed(ev.text)
            elif isinstance(ev, ToolUse):
                voice.sup.mark(w, "ttft")
                await speaker.flush()
                blocks.append({"type": "tool_use", "id": ev.id, "name": ev.name, "input": ev.input})
                if ev.name == DELEGATE.name:
                    delegated = Delegate.model_validate(ev.input)
                    continue
                if ev.name in (JOB_STEER.name, JOB_CANCEL.name):
                    routed.append((ev, await _route(voice, w, ev)))
                    continue
                if ev.name in MEMORY_TOOLS:
                    content = await _memory(voice, w, ev)
                    routed.append((ev, content))
                    if content == NOTHING_SAVED:
                        await speaker.say("Actually, I didn't have anything like that saved.")
                    continue
                tools_t0 = tools_t0 or rt.clock.monotonic()
                spec = BY_NAME[ev.name]
                call = voice.call_device(w, spec, ev.input, say=speaker.say)
                calls.append((ev, asyncio.create_task(call)))
            elif isinstance(ev, Restart):
                speaker.splitter.reset()
                await voice.cue(w, "heard")  # bridge while the next model starts over
                await voice.sup.incident(
                    w, stage="llm", error=ev.reason, remedy="bridge", outcome="recovered"
                )
            elif isinstance(ev, Done):
                w.provider = ev.provider
        await speaker.flush()
    except ChainExhausted:
        for _, task in calls:
            task.cancel()
        await voice.fail(w, "unreachable", stage="llm", error="chain exhausted")
        return
    finally:
        await stream.aclose()

    job_note = ""
    if delegated is not None:
        if not speaker.spoken:
            await speaker.say(delegated.ack)
        note_for_job = volatile_context(
            ctx,
            utc_offset_min,
            rt.clock.now(),
            origin=w.device_id,
            remembered=[*ctx.profile, *ctx.memories],  # the agent's system prompt has no profile
        )
        job = await voice.jobs.start(w, ctx, delegated.task, user_text, note_for_job)
        job_note = f"Started a background job for it ({job.title}). It reports back when done."

    results: list[dict[str, Any]] = []
    failed = False
    for use, task in calls:
        ok, content = await task
        failed = failed or not ok
        results.append(
            {"type": "tool_result", "tool_use_id": use.id, "content": content, "is_error": not ok}
        )
    if delegated is not None:
        results.append(
            {
                "type": "tool_result",
                "tool_use_id": next(b["id"] for b in blocks if b["name"] == DELEGATE.name),
                "content": job_note,
                "is_error": False,
            }
        )
    for use, content in routed:
        results.append(
            {"type": "tool_result", "tool_use_id": use.id, "content": content, "is_error": False}
        )

    turn: list[tuple[str, list[dict[str, Any]]]] = [
        ("user", [{"type": "text", "text": user_text}]),
        *((m["role"], m["content"]) for m in after or []),
    ]
    said = [{"type": "text", "text": speaker.text()}] if speaker.spoken else []
    if said or blocks:
        turn.append(("assistant", [*said, *blocks]))
    if results:
        turn.append(("user", results))

    state: State = "answered"
    if calls and not failed:
        if rt.clock.monotonic() - tools_t0 <= FAST_DONE_S:
            await voice.cue(w, "done")
        else:
            done = await persona.phrase(rt.redis, w.user_id, "done")
            await speaker.say(done)
            turn.append(("assistant", [{"type": "text", "text": done}]))
    elif failed:
        state = "failed_explained"
        follow = await _explain_tools(voice, w, ctx, [*messages, *_as_llm(turn[-2:])])
        turn.append(("assistant", [{"type": "text", "text": follow}]))
    elif not speaker.spoken:  # whitespace only (gpt-oss does this): never leave them in silence
        state = "failed_explained"
        sorry = await persona.phrase(rt.redis, w.user_id, "stuck")
        await speaker.say(sorry, "serious")
        turn.append(("assistant", [{"type": "text", "text": sorry}]))

    ids = await voice.store(w, ctx, turn)  # before the final marker: a follow-up sees this turn
    voice.sup.finish(w, state)
    await voice.end(w)
    if ids and not after and not any(u.name in MEMORY_TOOLS for u, _ in routed):
        voice.learn(w, ctx, user_text, speaker.text(), ids[0])


async def _route(voice: Voice, w: Watch, use: ToolUse) -> str:
    """§6.4 steer / interrupt, decided by the reflex, applied to the job right away."""
    jobs = voice.jobs
    hint = use.input.get("job") if isinstance(use.input.get("job"), str) else None
    job = jobs.find(w.user_id, hint)
    if job is None:
        return "No job is running."
    if use.name == JOB_CANCEL.name:
        await jobs.cancel(job)
        return f"Stopped: {job.title}."
    jobs.steer(job, str(use.input.get("message", ""))[:500])
    return f"Passed it on to the job: {job.title}."


NOTHING_SAVED = "Nothing like that was saved."


async def _memory(voice: Voice, w: Watch, use: ToolUse) -> str:
    """remember / forget from the reflex: run in the brain right away, like job_steer."""
    from app.capabilities import hooks  # hooks → runtime → … → reflex: imported late

    spec = MEMORY_TOOLS[use.name]
    try:
        inp = spec.validate(use.input)
        assert spec.handler is not None
        call = hooks.Call(voice.rt, w.user_id, None, None, spec, inp)
        return str(await spec.handler(call, inp))
    except Exception:
        logging.getLogger(__name__).warning("reflex memory tool failed", exc_info=True)
        return f"{spec.name} didn't work this time."


def _as_llm(turn: list[tuple[str, list[dict[str, Any]]]]) -> list[LlmMessage]:
    return [{"role": role, "content": content} for role, content in turn]


async def _explain_tools(voice: Voice, w: Watch, ctx: Context, messages: list[LlmMessage]) -> str:
    """A second, tool-less turn: the model says what failed and offers a next step (§4.4)."""
    speaker = Speaker(voice, w)
    stream = voice.rt.llm.stream(
        "reflex", system=system(ctx), messages=messages, allow_training=ctx.allow_training
    )
    try:
        async for ev in stream:
            if isinstance(ev, TextDelta):
                await speaker.feed(ev.text)
            elif isinstance(ev, Restart):
                speaker.splitter.reset()
        await speaker.flush()
    except ChainExhausted:
        pass
    finally:
        await stream.aclose()
    if not speaker.spoken:
        await speaker.say(await persona.phrase(voice.rt.redis, w.user_id, "failure"), "serious")
    return speaker.text()


def tool_content(output: Any) -> str:
    return output if isinstance(output, str) else json.dumps(output, default=str)[:2000]
