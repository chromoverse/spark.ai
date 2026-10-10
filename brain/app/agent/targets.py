"""Which device runs a device tool (REDESIGN §26.3): an explicit name or kind ("my phone"), else the
origin, else an online device that can do it (said out loud). Two matches → ask once, and the
answer becomes the default for that word. An offline target → an offer to queue the call; "yes"
stores it, and it runs when the device is back (1 h at most)."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from app.core.runtime import Runtime
from app.db.models import Device, QueuedAction
from app.gateway import presence
from app.tools.spec import ToolSpec

AMBIGUOUS_TTL_S = 600  # "which phone?" stays open this long
OFFER_TTL_S = 300
QUEUE_FOR = timedelta(hours=1)
KINDS = {
    "phone": ("mobile", "adb_phone"),
    "mobile": ("mobile", "adb_phone"),
    "cell": ("mobile", "adb_phone"),
    "laptop": ("desktop",),
    "computer": ("desktop",),
    "pc": ("desktop",),
    "desktop": ("desktop",),
}
_FILLER = re.compile(r"^(?:on |from |to )?(?:my |the |this )?")


@dataclass(frozen=True)
class Known:
    id: uuid.UUID
    name: str
    kind: str
    capabilities: frozenset[str]
    defaults: tuple[str, ...]
    online: bool


@dataclass(frozen=True)
class Target:
    device: Known
    announce: str | None = None  # said when the target isn't the device the user spoke to


class Unresolved(Exception):
    """A message the model can act on: say it, ask which device, or offer to queue."""

    def __init__(self, message: str, offline: Known | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.offline = offline  # the target exists but is offline: offer to queue


async def devices(rt: Runtime, user_id: uuid.UUID) -> list[Known]:
    async with rt.db() as db:
        rows = (
            await db.scalars(
                select(Device).where(Device.user_id == user_id).order_by(Device.created_at)
            )
        ).all()
    online = await presence.online(rt, user_id)
    return [
        Known(
            d.id,
            d.name,
            d.kind,
            frozenset(d.capabilities),
            tuple(d.is_default_for),
            str(d.id) in online,
        )
        for d in rows
    ]


def word_of(hint: str) -> str:
    return _FILLER.sub("", hint.strip().lower()).strip(" .?!'")


def _spoken_kind(d: Known) -> str:
    return "phone" if d.kind in ("mobile", "adb_phone") else d.name


async def resolve(
    rt: Runtime,
    user_id: uuid.UUID,
    origin: uuid.UUID,
    spec: ToolSpec,
    hint: str | None,
    *,
    exclude: frozenset[uuid.UUID] = frozenset(),
) -> Target:
    """Raises Unresolved with what to tell the user. Offline targets record an offer."""
    mine = [d for d in await devices(rt, user_id) if d.id not in exclude]
    able = [d for d in mine if spec.requires <= d.capabilities]
    if hint and word_of(hint):
        target = await _explicit(rt, user_id, mine, word_of(hint))
        if not spec.requires <= target.capabilities:
            raise Unresolved(f"{target.name} can't do that ({spec.name}).")
        return _online(target, None)
    here = next((d for d in able if d.id == origin), None)
    if here is not None:
        return _online(here, None)
    if not able:
        raise Unresolved("None of your devices can do that yet.")
    live = [d for d in able if d.online]
    pick = (live or able)[0]
    verb = "Sending it" if spec.risk.value == "external" else "Doing it"
    return _online(pick, f"{verb} from your {_spoken_kind(pick)}.")


async def _explicit(rt: Runtime, user_id: uuid.UUID, mine: list[Known], word: str) -> Known:
    named = [d for d in mine if d.name.lower() == word] or [
        d for d in mine if word in d.name.lower()
    ]
    if len(named) == 1:
        await _settle(rt, user_id, named[0])
        return named[0]
    kinds = KINDS.get(word.rstrip("s"), ())
    by_default = [d for d in mine if word in d.defaults]
    if len(by_default) == 1:
        return by_default[0]
    candidates = named or [d for d in mine if d.kind in kinds]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        names = ", ".join(d.name for d in mine) or "none yet"
        raise Unresolved(f"I don't know a device called {word}. Your devices: {names}.")
    await rt.redis.set(
        f"ambiguous:{user_id}:{word}",
        json.dumps([str(d.id) for d in candidates]),
        ex=AMBIGUOUS_TTL_S,
    )
    names = " and ".join(sorted(d.name for d in candidates))
    raise Unresolved(f"Two or more devices match '{word}': {names}. Ask the user which one.")


async def _settle(rt: Runtime, user_id: uuid.UUID, chosen: Known) -> None:
    """E3: the answer to "which phone?" becomes the default for that word."""
    for word in KINDS:
        key = f"ambiguous:{user_id}:{word}"
        raw = await rt.redis.get(key)
        if raw is None or str(chosen.id) not in json.loads(raw):
            continue
        await rt.redis.delete(key)
        async with rt.db() as db:
            rows = (await db.scalars(select(Device).where(Device.user_id == user_id))).all()
            for d in rows:
                kept = [w for w in d.is_default_for if w != word]
                d.is_default_for = sorted({*kept, word}) if d.id == chosen.id else kept
            await db.commit()


def _online(d: Known, announce: str | None) -> Target:
    if d.online:
        return Target(d, announce)
    raise Unresolved(f"{d.name} is offline.", offline=d)


async def offer(
    rt: Runtime,
    user_id: uuid.UUID,
    origin: uuid.UUID,
    d: Known,
    spec: ToolSpec,
    inp: dict[str, Any],
) -> str:
    """E2: remembers the call so a "yes" can queue it; returns what to tell the model."""
    payload = {"tool": spec.name, "input": inp, "device_id": str(d.id), "device": d.name}
    await rt.redis.set(
        f"offer:{user_id}", json.dumps(payload | {"origin": str(origin)}), ex=OFFER_TTL_S
    )
    return (
        f"{d.name} is offline. Ask if they want it done when it's back online "
        "(it waits up to an hour)."
    )


async def pending_offer(rt: Runtime, user_id: uuid.UUID) -> dict[str, Any] | None:
    raw = await rt.redis.get(f"offer:{user_id}")
    return json.loads(raw) if raw else None


async def accept_offer(rt: Runtime, user_id: uuid.UUID, yes: bool) -> str:
    raw = await rt.redis.getdel(f"offer:{user_id}")
    if raw is None:
        return "Okay."
    o = json.loads(raw)
    if not yes:
        return "Okay, never mind."
    async with rt.db() as db:
        db.add(
            QueuedAction(
                user_id=user_id,
                target_device_id=uuid.UUID(o["device_id"]),
                origin_device_id=uuid.UUID(o["origin"]),
                tool_call={"tool": o["tool"], "input": o["input"]},
                expires_at=rt.clock.now() + QUEUE_FOR,
            )
        )
        await db.commit()
    return f"Okay, I'll do it when your {o['device']} is back online."


async def due(rt: Runtime, user_id: uuid.UUID, device_id: uuid.UUID) -> list[QueuedAction]:
    """Unexpired, unfired calls for a device that just came online; marked fired here."""
    now = rt.clock.now()
    async with rt.db() as db:
        rows = list(
            (
                await db.scalars(
                    select(QueuedAction)
                    .where(
                        QueuedAction.user_id == user_id,
                        QueuedAction.target_device_id == device_id,
                        QueuedAction.fired_at.is_(None),
                        QueuedAction.expires_at > now,
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for row in rows:
            row.fired_at = now
        await db.commit()
    return rows
