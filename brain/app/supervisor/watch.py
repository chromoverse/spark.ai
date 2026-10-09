"""Supervisor core (REDESIGN §19): every signal gets a watch with a deadline and must reach a
terminal state. A sweep every 5 s finds watches past their deadline, cancels their work, and
explains the failure to the user. Spans on the watch become the per-signal latency trace (§13).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

from app.core.runtime import Runtime
from app.db.models import Incident

logger = logging.getLogger(__name__)

State = Literal["open", "answered", "cancelled", "failed_explained"]
SWEEP_S = 5.0
SIGNAL_DEADLINE_S = 20.0  # reflex + quick tools + one follow-up turn
HEARD_CUE_S = 0.5  # no first sentence by then → first audio will likely miss 1 s (§4.4)
DEDUPE_S = 300


@dataclass
class Watch:
    user_id: uuid.UUID
    device_id: uuid.UUID
    signal_id: str
    t0: float  # clock.monotonic() when the brain got the signal
    deadline_s: float = SIGNAL_DEADLINE_S
    tier: int = 2
    state: State = "open"
    task: asyncio.Task[None] | None = None
    spans: dict[str, float] = field(default_factory=dict)  # ms since t0
    provider: str | None = None

    @property
    def key(self) -> tuple[uuid.UUID, str]:
        return (self.user_id, self.signal_id)


Explain = Callable[[Watch, str], Awaitable[None]]


class Supervisor:
    def __init__(self, rt: Runtime, explain: Explain) -> None:
        self.rt = rt
        self.explain = explain  # speaks + shows a persona-voiced failure (§19.2 step 8)
        self.watches: dict[tuple[uuid.UUID, str], Watch] = {}

    async def open(self, user_id: uuid.UUID, device_id: uuid.UUID, signal_id: str) -> Watch | None:
        """None when this signal id was already seen (a retried send): handle it once."""
        fresh = await self.rt.redis.set(f"signal:{user_id}:{signal_id}", 1, nx=True, ex=DEDUPE_S)
        if not fresh:
            return None
        w = Watch(user_id, device_id, signal_id, self.rt.clock.monotonic())
        self.watches[w.key] = w
        return w

    def mark(self, w: Watch, span: str) -> None:
        """Records the first time a span happens (ms since the signal arrived)."""
        if span not in w.spans:
            w.spans[span] = round((self.rt.clock.monotonic() - w.t0) * 1000, 1)

    def finish(self, w: Watch, state: State) -> None:
        if w.state != "open":
            return
        w.state = state
        self.mark(w, "end")
        self.watches.pop(w.key, None)
        logger.info(
            "signal done",
            extra={
                "signal_id": w.signal_id,
                "state": state,
                "tier": w.tier,
                "provider": w.provider,
                "spans": w.spans,
            },
        )

    def latest(self, user_id: uuid.UUID, device_id: uuid.UUID | None = None) -> Watch | None:
        mine = [
            w
            for w in self.watches.values()
            if w.user_id == user_id and (device_id is None or w.device_id == device_id)
        ]
        return max(mine, key=lambda w: w.t0, default=None)

    def get(self, user_id: uuid.UUID, signal_id: str) -> Watch | None:
        return self.watches.get((user_id, signal_id))

    async def cancel(self, w: Watch) -> None:
        if w.task is not None and not w.task.done() and w.task is not asyncio.current_task():
            w.task.cancel()
            await asyncio.wait({w.task})
        self.finish(w, "cancelled")

    async def heard_cue(self, w: Watch, cue: Callable[[], Awaitable[None]]) -> None:
        """Bridges the silence (§19.2 step 3) when the first sentence is late."""
        await self.rt.clock.sleep(HEARD_CUE_S)
        if w.state == "open" and "first_delta" not in w.spans:
            self.mark(w, "heard_cue")
            await cue()

    async def incident(
        self,
        w: Watch | None,
        *,
        user_id: uuid.UUID | None = None,
        device_id: uuid.UUID | None = None,
        stage: str,
        error: str,
        remedy: str,
        outcome: str,
        engine: str | None = None,
    ) -> None:
        try:
            async with self.rt.db() as db:
                db.add(
                    Incident(
                        user_id=w.user_id if w else user_id,
                        device_id=w.device_id if w else device_id,
                        stage=stage,
                        engine_or_provider=engine,
                        error=error[:500],
                        remedy=remedy,
                        outcome=outcome,
                        signal_id=w.signal_id if w else None,
                        ts=self.rt.clock.now(),
                    )
                )
                await db.commit()
        except Exception:
            logger.warning("incident not stored", exc_info=True)

    async def sweep(self) -> None:
        now = self.rt.clock.monotonic()
        for w in list(self.watches.values()):
            if w.state == "open" and now - w.t0 > w.deadline_s:
                logger.warning("signal past deadline", extra={"signal_id": w.signal_id})
                if w.task is not None and not w.task.done():
                    w.task.cancel()
                    await asyncio.wait({w.task})
                if w.state != "open":
                    continue  # the task reached a terminal state while being cancelled
                self.finish(w, "failed_explained")
                await self.explain(w, "deadline")
                await self.incident(
                    w,
                    stage="deadline",
                    error=f"no terminal state after {w.deadline_s:.0f}s",
                    remedy="explain",
                    outcome="failed_explained",
                    engine=w.provider,
                )

    async def run(self) -> None:
        while True:
            await self.rt.clock.sleep(SWEEP_S)
            try:
                await self.sweep()
            except Exception:
                logger.error("supervisor sweep failed", exc_info=True)
