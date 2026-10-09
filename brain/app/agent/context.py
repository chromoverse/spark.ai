"""What a turn needs from the database (thread, recent turns, settings, device) and how a finished
turn is stored. Loaded once per signal, prefetched on `signal.partial` (REDESIGN §4.2)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from app.core.runtime import Runtime
from app.db.models import Device, Message, Thread, UserSettings
from app.llm.types import Message as LlmMessage

THREAD_IDLE = timedelta(minutes=30)  # a signal after this much quiet starts a new thread
RECENT_MESSAGES = 8  # lean prompts: Groq's free tier allows 8K tokens/min


@dataclass
class Context:
    thread_id: uuid.UUID | None
    history: list[LlmMessage]
    device_name: str
    allow_training: bool = False
    verbosity: str = "normal"
    address_as: str | None = None
    language: str = "en"
    extra: dict[str, Any] = field(default_factory=dict)


def _flatten(m: Message) -> LlmMessage | None:
    """Stored content blocks → one text turn. Tool calls become a short note; tool results are
    dropped. Keeps history cheap and never leaves a tool_use without its result."""
    parts: list[str] = []
    for b in m.content:
        if b.get("type") == "text" and b.get("text"):
            parts.append(b["text"])
        elif b.get("type") == "tool_use":
            parts.append(f"[{b['name']} {json.dumps(b.get('input', {}))}]")
    if not parts:
        return None
    return {"role": m.role, "content": [{"type": "text", "text": " ".join(parts)}]}


async def load(rt: Runtime, user_id: uuid.UUID, device_id: uuid.UUID) -> Context:
    async with rt.db() as db:
        thread = await db.scalar(
            select(Thread)
            .where(
                Thread.user_id == user_id,
                Thread.last_message_at > rt.clock.now() - THREAD_IDLE,
            )
            .order_by(Thread.last_message_at.desc())
            .limit(1)
        )
        history: list[LlmMessage] = []
        if thread is not None:
            rows = (
                await db.scalars(
                    select(Message)
                    .where(Message.thread_id == thread.id, Message.user_id == user_id)
                    .order_by(Message.created_at.desc(), Message.id.desc())
                    .limit(RECENT_MESSAGES)
                )
            ).all()
            history = [f for m in reversed(rows) if (f := _flatten(m)) is not None]
            while history and history[0]["role"] != "user":
                history.pop(0)
        settings = await db.scalar(select(UserSettings).where(UserSettings.user_id == user_id))
        device = await db.scalar(
            select(Device).where(Device.id == device_id, Device.user_id == user_id)
        )
    ctx = Context(
        thread_id=thread.id if thread else None,
        history=history,
        device_name=device.name if device else "this device",
    )
    if settings is not None:
        ctx.allow_training = settings.allow_training_providers
        ctx.verbosity = settings.verbosity
        ctx.address_as = settings.address_as
        ctx.language = settings.language
    return ctx


async def store_turn(
    rt: Runtime,
    user_id: uuid.UUID,
    device_id: uuid.UUID,
    ctx: Context,
    *,
    signal_id: str,
    tier: int,
    messages: list[tuple[str, list[dict[str, Any]]]],
) -> uuid.UUID:
    """Appends (role, content blocks) rows to the active thread, creating it if needed."""
    now = rt.clock.now()
    async with rt.db() as db:
        thread_id = ctx.thread_id
        if thread_id is None:
            thread = Thread(user_id=user_id, last_message_at=now)
            db.add(thread)
            await db.flush()
            thread_id = thread.id
        else:
            thread = await db.get_one(Thread, thread_id)
            thread.last_message_at = now
        for i, (role, content) in enumerate(messages):
            db.add(
                Message(
                    thread_id=thread_id,
                    user_id=user_id,
                    role=role,
                    content=content,
                    tier=tier,
                    device_id=device_id,
                    signal_id=signal_id,
                    # explicit, ordered timestamps: rows of one turn share a transaction
                    created_at=now + timedelta(microseconds=i),
                )
            )
        await db.commit()
    ctx.thread_id = thread_id
    return thread_id
