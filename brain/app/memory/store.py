"""Long-term memory (REDESIGN §8): save with dedupe, hybrid search, the profile, forget, decay.

Search fuses two ranked lists by reciprocal rank: the nearest embeddings (pgvector HNSW, cosine)
and full-text matches (Postgres `simple` config, any word), then weighs importance. The profile is
the user's most important memories, always in the prompt; it's rebuilt from the table on any
change, so a forgotten memory leaves it at once."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Float,
    case,
    cast,
    delete,
    func,
    literal,
    or_,
    select,
    union_all,
    update,
)
from sqlalchemy.dialects.postgresql import TSQUERY

from app.core.runtime import Runtime
from app.db.models import Memory

logger = logging.getLogger(__name__)

KINDS = ("preference", "person", "routine", "fact", "correction")
TOP_K = 8  # §21
POOL = 20  # candidates from each side before fusing
RRF_K = 60
PROFILE_CHARS = 1200  # ≤ 300 tokens in every prompt (§21)
PROFILE_TTL_S = 3600
LOW = 0.4  # below this importance, a memory lapses after UNUSED_FOR without being used
UNUSED_FOR = timedelta(days=90)
RECENT = timedelta(days=7)  # used this recently: ranks a little higher
_STOP = frozenset(
    "a about all also an and any are as at be been but by can could did do does for from get "
    "got had has have he her his how i i'm if in into is it its just know let me my no not now "
    "of on or our please really she should so some tell than that the their them then there "
    "they this to up us user was we what when where which who why will with would you your hey "
    "spark ok okay".split()
)


@dataclass(frozen=True)
class Found:
    id: uuid.UUID
    kind: str
    text: str


def _live(now: datetime, *, confirmed_only: bool = True) -> list[ColumnElement[bool]]:
    alive = or_(Memory.expires_at.is_(None), Memory.expires_at > now)
    return [alive, Memory.confirmed.is_(True)] if confirmed_only else [alive]


def _expiry(now: datetime, importance: float) -> datetime | None:
    return now + UNUSED_FOR if importance < LOW else None


def _words(text: str) -> list[str]:
    """Search words for to_tsquery: \\w+ only, so nothing in them is tsquery syntax."""
    seen = dict.fromkeys(w for w in re.findall(r"\w+", text.lower()) if w not in _STOP)
    return [w for w in seen if len(w) > 1][:12]


def _distance(vec: list[float]) -> ColumnElement[float]:
    return Memory.embedding.op("<=>", return_type=Float)(vec)


async def forget_profile(rt: Runtime, user_id: uuid.UUID) -> None:
    await rt.redis.delete(f"hot:{user_id}:profile")


async def save(
    rt: Runtime,
    user_id: uuid.UUID,
    text: str,
    kind: str,
    importance: float,
    *,
    confirmed: bool = True,
    source_message_id: uuid.UUID | None = None,
    replaces: uuid.UUID | None = None,
) -> Memory:
    """Upsert. A memory that replaces another (a correction, a changed preference) or says the
    same thing updates that row, newest wording wins; anything else is a new row. An unconfirmed
    one never rewrites a confirmed one."""
    text = " ".join(text.split())[:500]
    kind = kind if kind in KINDS else "fact"
    importance = min(1.0, max(0.0, importance))
    vecs = await rt.embedder.embed([text], query=False)
    vec = vecs[0] if vecs else None
    now = rt.clock.now()
    async with rt.db() as db:
        await db.execute(delete(Memory).where(Memory.user_id == user_id, Memory.expires_at <= now))
        mine = [Memory.user_id == user_id]
        if not confirmed:
            mine.append(Memory.confirmed.is_(False))
        row = None
        if replaces is not None:
            row = await db.scalar(select(Memory).where(Memory.id == replaces, *mine))
        if row is None and vec is not None:
            d = _distance(vec)
            hit = (
                await db.execute(
                    select(Memory, d)
                    .where(*mine, Memory.embedding.is_not(None))
                    .order_by(d)
                    .limit(1)
                )
            ).first()
            if hit is not None and 1 - hit[1] >= rt.embedder.same:
                row = hit[0]
        if row is None:
            row = await db.scalar(
                select(Memory).where(*mine, func.lower(Memory.text) == text.lower()).limit(1)
            )
        if row is None:
            row = Memory(user_id=user_id, importance=importance, confirmed=confirmed)
            db.add(row)
        row.text, row.kind, row.embedding = text, kind, vec
        row.importance = max(row.importance, importance)
        row.confirmed = row.confirmed or confirmed  # the user said it themselves
        row.expires_at = _expiry(now, row.importance)
        row.source_message_id = source_message_id or row.source_message_id
        await db.commit()
        await db.refresh(row)
    await forget_profile(rt, user_id)
    return row


async def search(
    rt: Runtime,
    user_id: uuid.UUID,
    query: str,
    k: int = TOP_K,
    *,
    confirmed_only: bool = True,
    floor: bool = True,
    touch: bool = True,
) -> list[Found]:
    """Hybrid top-k for `query`. Vector matches below the related floor are dropped (e5 scores
    unrelated lines ~0.75); word matches always count. Hits get `last_used_at` (decay), written
    after the answer so the turn doesn't wait on a commit."""
    vecs = await rt.embedder.embed([query], query=True) if query.strip() else None
    words = _words(query)
    now = rt.clock.now()
    live = [Memory.user_id == user_id, *_live(now, confirmed_only=confirmed_only)]
    # never the embedding itself: nobody here reads it
    cols = (Memory.id, Memory.kind, Memory.text, Memory.importance, Memory.last_used_at)
    arms = []
    if vecs:  # nearest first; HNSW (iterative scan, set per connection in Runtime)
        d = _distance(vecs[0])
        arms.append(
            select(*cols, literal("v").label("arm"), d.label("score"))
            .where(*live, Memory.embedding.is_not(None))
            .order_by(d)
            .limit(POOL)
        )
    if words:  # one tsquery value, not to_tsquery() per row; \w+ words are valid lexemes
        tsq = cast(" | ".join(words), TSQUERY)
        rank = func.ts_rank(Memory.tsv, tsq)
        arms.append(
            select(*cols, literal("w").label("arm"), (-rank).label("score"))
            .where(*live, Memory.tsv.bool_op("@@")(tsq))
            .order_by(rank.desc())
            .limit(POOL)
        )
    if not arms:
        return []
    stmt = arms[0] if len(arms) == 1 else union_all(*(select(a.subquery()) for a in arms))
    async with rt.db() as db:  # both arms in one round trip
        found = sorted((await db.execute(stmt)).all(), key=lambda r: (r.arm, r.score))
    scores: dict[uuid.UUID, float] = {}
    rows: dict[uuid.UUID, Any] = {}
    for arm in ("v", "w"):
        hits = [r for r in found if r.arm == arm]
        if arm == "v" and floor:
            hits = [r for r in hits if 1 - r.score >= rt.embedder.related]
        for i, r in enumerate(hits):
            rows[r.id] = r
            scores[r.id] = scores.get(r.id, 0.0) + 1 / (RRF_K + i + 1)

    def weight(r: Any) -> float:
        used = r.last_used_at is not None and now - r.last_used_at < RECENT
        return scores[r.id] * (1 + float(r.importance)) * (1.1 if used else 1.0)

    best = sorted(rows.values(), key=weight, reverse=True)[:k]
    if best and touch:
        task = asyncio.create_task(_touch(rt, user_id, [(r.id, r.importance) for r in best], now))
        _touching.add(task)
        task.add_done_callback(_touching.discard)
    return [Found(r.id, r.kind, r.text) for r in best]


_touching: set[asyncio.Task[None]] = set()


async def _touch(
    rt: Runtime, user_id: uuid.UUID, hits: list[tuple[uuid.UUID, float]], now: datetime
) -> None:
    """Used now: lapsing memories get another UNUSED_FOR (one statement, off the hot path)."""
    lapsing = [i for i, imp in hits if imp < LOW]
    try:
        async with rt.db() as db:
            await db.execute(
                update(Memory)
                .where(Memory.user_id == user_id, Memory.id.in_([i for i, _ in hits]))
                .values(
                    last_used_at=now,
                    expires_at=case(
                        (Memory.id.in_(lapsing), now + UNUSED_FOR), else_=Memory.expires_at
                    )
                    if lapsing
                    else Memory.expires_at,
                )
            )
            await db.commit()
    except Exception:
        logger.warning("memory use not recorded", exc_info=True)


async def profile(rt: Runtime, user_id: uuid.UUID) -> list[Found]:
    """The most important memories that fit in PROFILE_CHARS, cached in Redis for an hour and
    dropped on any change."""
    key = f"hot:{user_id}:profile"
    if (cached := await rt.redis.get(key)) is not None:
        return [Found(uuid.UUID(i), k, t) for i, k, t in json.loads(cached)]
    async with rt.db() as db:
        rows = await db.scalars(
            select(Memory)
            .where(Memory.user_id == user_id, *_live(rt.clock.now()))
            .order_by(Memory.importance.desc(), Memory.updated_at.desc())
            .limit(60)
        )
        out: list[Found] = []
        size = 0
        for m in rows:
            if size + len(m.text) + 1 > PROFILE_CHARS:
                break
            out.append(Found(m.id, m.kind, m.text))
            size += len(m.text) + 1
    await rt.redis.set(
        key, json.dumps([[str(f.id), f.kind, f.text] for f in out]), ex=PROFILE_TTL_S
    )
    return out


async def forget(rt: Runtime, user_id: uuid.UUID, what: str) -> str | None:
    """Deletes the closest memory to `what` (its embedding goes with the row); its text, or
    None when nothing comes close."""
    hits = await search(rt, user_id, what, 1, confirmed_only=False, touch=False)
    if not hits:
        return None
    await delete_one(rt, user_id, hits[0].id)
    return hits[0].text


async def delete_one(rt: Runtime, user_id: uuid.UUID, memory_id: uuid.UUID) -> bool:
    async with rt.db() as db:
        gone = await db.execute(
            delete(Memory)
            .where(Memory.id == memory_id, Memory.user_id == user_id)
            .returning(Memory.id)
        )
        await db.commit()
    await forget_profile(rt, user_id)
    return gone.first() is not None


async def edit(
    rt: Runtime, user_id: uuid.UUID, memory_id: uuid.UUID, changes: dict[str, Any]
) -> Memory | None:
    """The Memory page: new wording (re-embedded), kind, importance, or the user's OK."""
    if "text" in changes:
        changes["text"] = " ".join(str(changes["text"]).split())[:500]
        vecs = await rt.embedder.embed([changes["text"]], query=False)
        changes["embedding"] = vecs[0] if vecs else None
    if "importance" in changes:
        changes["expires_at"] = _expiry(rt.clock.now(), changes["importance"])
    async with rt.db() as db:
        row = await db.scalar(
            update(Memory)
            .where(Memory.id == memory_id, Memory.user_id == user_id)
            .values(**changes)
            .returning(Memory)
        )
        await db.commit()
    await forget_profile(rt, user_id)
    return row


def render(found: list[Found]) -> str:
    return " ".join(f.text for f in found)
