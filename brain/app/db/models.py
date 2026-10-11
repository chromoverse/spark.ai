"""Tables (DATABASE.md). Every user-owned row has user_id; queries filter by it."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Computed,
    ForeignKey,
    Identity,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import CITEXT, REAL, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, HalfVec, Timestamps, uuid7


def _user_fk() -> ForeignKey:
    return ForeignKey("users.id", ondelete="CASCADE")


class User(Timestamps, Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    email: Mapped[str] = mapped_column(CITEXT, unique=True)
    name: Mapped[str | None]
    nickname: Mapped[str | None]
    plan: Mapped[str] = mapped_column(server_default="free")


class AuthIdentity(Timestamps, Base):
    __tablename__ = "auth_identities"
    __table_args__ = (UniqueConstraint("provider", "subject"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(_user_fk(), index=True)
    provider: Mapped[str]  # email | google
    subject: Mapped[str]


class OtpCode(Timestamps, Base):
    __tablename__ = "otp_codes"
    __table_args__ = (Index(None, "email", "expires_at"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    email: Mapped[str] = mapped_column(CITEXT)
    code_hash: Mapped[str]
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    expires_at: Mapped[datetime]
    consumed_at: Mapped[datetime | None]


class Device(Timestamps, Base):
    __tablename__ = "devices"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(_user_fk(), index=True)
    kind: Mapped[str]  # desktop | mobile | adb_phone
    name: Mapped[str]
    platform: Mapped[str | None]
    parent_device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE")
    )
    capabilities: Mapped[list[Any]] = mapped_column(server_default=text("'[]'::jsonb"))
    hardware: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    engine_plan: Mapped[dict[str, Any] | None]
    is_default_for: Mapped[list[str]] = mapped_column(server_default=text("'{}'::text[]"))
    app_version: Mapped[str | None]
    last_seen_at: Mapped[datetime | None]


class Session(Timestamps, Base):
    __tablename__ = "sessions"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(_user_fk(), index=True)
    device_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    refresh_hash: Mapped[str] = mapped_column(unique=True)
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    last_used_at: Mapped[datetime | None]


class UserSettings(Timestamps, Base):
    __tablename__ = "user_settings"
    user_id: Mapped[uuid.UUID] = mapped_column(_user_fk(), primary_key=True)
    language: Mapped[str] = mapped_column(server_default="en")
    auto_detect_language: Mapped[bool] = mapped_column(server_default=text("false"))
    voice: Mapped[str | None]
    verbosity: Mapped[str] = mapped_column(server_default="normal")
    address_as: Mapped[str | None]
    permission_mode: Mapped[str] = mapped_column(server_default="default")
    allow_training_providers: Mapped[bool] = mapped_column(server_default=text("false"))
    models: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))


class Thread(Timestamps, Base):
    __tablename__ = "threads"
    __table_args__ = (
        Index("ix_threads_user_id_last_message_at", "user_id", text("last_message_at DESC")),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(_user_fk())
    title: Mapped[str | None]
    last_message_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Message(Timestamps, Base):
    __tablename__ = "messages"
    __table_args__ = (Index(None, "thread_id", "created_at"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    thread_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("threads.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(_user_fk(), index=True)
    role: Mapped[str]
    content: Mapped[list[Any]]  # content blocks
    tier: Mapped[int | None] = mapped_column(SmallInteger)
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL")
    )
    signal_id: Mapped[str | None]


class Event(Base):
    """Sync log (§10). seq is the event id devices send back in sync.resume. 7-day retention."""

    __tablename__ = "events"
    __table_args__ = (Index(None, "user_id", "seq"),)
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(_user_fk())
    type: Mapped[str]
    payload: Mapped[dict[str, Any]]
    ts: Mapped[datetime] = mapped_column(server_default=func.now())


class AuditLog(Base):
    """Append-only."""

    __tablename__ = "audit_log"
    __table_args__ = (Index(None, "user_id", "ts"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID | None] = mapped_column(_user_fk())
    actor: Mapped[str]  # user | device:<id> | system
    action: Mapped[str]
    target: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    ts: Mapped[datetime] = mapped_column(server_default=func.now())


class Incident(Base):
    """Supervisor and watchdog incidents (REDESIGN §19.3): what failed, which remedy ran, and
    how it ended. 90-day retention."""

    __tablename__ = "incidents"
    __table_args__ = (Index(None, "user_id", "ts"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(_user_fk())
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL")
    )
    stage: Mapped[str]  # llm | tool | tts | stt | wake | deadline
    engine_or_provider: Mapped[str | None]
    error: Mapped[str]
    remedy: Mapped[str]  # hedge | switch | bridge | degrade | replan | explain
    outcome: Mapped[str]  # answered | failed_explained | cancelled | recovered
    signal_id: Mapped[str | None]
    ts: Mapped[datetime] = mapped_column(server_default=func.now())


# ── R2: jobs, approvals, artifacts, queued actions, permission rules (DATABASE.md §2, §4) ──


def _set_null(table: str) -> ForeignKey:
    return ForeignKey(f"{table}.id", ondelete="SET NULL")


ACTIVE_JOB = "status IN ('queued', 'running', 'waiting')"


class Job(Timestamps, Base):
    """One delegated task (REDESIGN §6.1). Persisted at every step; a brain restart fails the
    active ones with an explanation instead of dropping them."""

    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_user_id_created_at", "user_id", text("created_at DESC")),
        Index("ix_jobs_active", "user_id", postgresql_where=text(ACTIVE_JOB)),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(_user_fk())
    thread_id: Mapped[uuid.UUID | None] = mapped_column(_set_null("threads"))
    device_id: Mapped[uuid.UUID | None] = mapped_column(_set_null("devices"))  # origin
    signal_id: Mapped[str | None]
    title: Mapped[str]
    status: Mapped[str] = mapped_column(
        server_default="queued"
    )  # queued|running|waiting|done|cancelled|failed
    effort: Mapped[str] = mapped_column(server_default="medium")
    todo: Mapped[list[Any]] = mapped_column(server_default=text("'[]'::jsonb"))
    eta_s: Mapped[int | None]
    provider_used: Mapped[str | None]
    usage: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    summary: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None]


class JobStep(Timestamps, Base):
    """One tool call of a job. `output` is the redacted, truncated result the model saw."""

    __tablename__ = "job_steps"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(_user_fk())
    tool: Mapped[str]
    input: Mapped[dict[str, Any]]
    output: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        server_default="running"
    )  # running|ok|error|denied|cancelled
    device_id: Mapped[uuid.UUID | None] = mapped_column(_set_null("devices"))
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None]
    error: Mapped[str | None]


class Approval(Timestamps, Base):
    """An ask (§7.2): sent to every online device, first answer wins, expires unanswered."""

    __tablename__ = "approvals"
    __table_args__ = (Index(None, "user_id", "created_at"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(_user_fk())
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    tool: Mapped[str]  # a tool name, or "plan" for plan approval
    summary: Mapped[str]
    risk: Mapped[str]
    inputs_preview: Mapped[dict[str, Any]]
    decision: Mapped[str | None]  # allow|deny|always|expired
    decided_by_device: Mapped[uuid.UUID | None] = mapped_column(_set_null("devices"))
    decided_at: Mapped[datetime | None]


class Artifact(Timestamps, Base):
    __tablename__ = "artifacts"
    __table_args__ = (Index(None, "user_id", "thread_id"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(_user_fk())
    thread_id: Mapped[uuid.UUID | None] = mapped_column(_set_null("threads"))
    job_id: Mapped[uuid.UUID | None] = mapped_column(_set_null("jobs"))
    device_id: Mapped[uuid.UUID | None] = mapped_column(_set_null("devices"))  # who made it
    kind: Mapped[str]  # text|file|image|table
    name: Mapped[str]
    mime: Mapped[str]
    size: Mapped[int] = mapped_column(BigInteger)
    storage_ref: Mapped[str]  # file name under ARTIFACTS_DIR
    preview: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    meta: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))


class QueuedAction(Timestamps, Base):
    """A device tool call waiting for its target to come online (§26.3), 1 h at most."""

    __tablename__ = "queued_actions"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(_user_fk())
    target_device_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    origin_device_id: Mapped[uuid.UUID | None] = mapped_column(_set_null("devices"))
    tool_call: Mapped[dict[str, Any]]  # {tool, input}
    expires_at: Mapped[datetime]
    fired_at: Mapped[datetime | None]


class PermissionRule(Timestamps, Base):
    """deny / ask / allow per tool, optionally for one device, with a glob on the tool's
    matched input field (REDESIGN §7.2): `file_delete` + `C:/Users/*/Downloads/**`."""

    __tablename__ = "permission_rules"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(_user_fk(), index=True)
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE")
    )
    tool: Mapped[str]
    pattern: Mapped[str] = mapped_column(server_default="")  # '' = every input
    decision: Mapped[str]  # deny|ask|allow


# ── R3: memory (DATABASE.md §3) ──


class Memory(Timestamps, Base):
    """A durable fact about the user (REDESIGN §8): pulled from their own words after a turn, or
    saved with `remember`. One the agent saved during a job waits for the user's OK (it may have
    read it somewhere), and stays out of prompts until then."""

    __tablename__ = "memories"
    __table_args__ = (
        Index(
            "ix_memories_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "halfvec_cosine_ops"},
        ),
        Index("ix_memories_tsv", "tsv", postgresql_using="gin"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(_user_fk(), index=True)
    kind: Mapped[str]  # preference | person | routine | fact | correction
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(
        HalfVec(384)
    )  # null until the model loads
    tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple'::regconfig, text)", persisted=True)
    )
    importance: Mapped[float] = mapped_column(REAL)
    confirmed: Mapped[bool] = mapped_column(server_default=true())  # `text` is a column here
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(_set_null("messages"))
    last_used_at: Mapped[datetime | None]
    expires_at: Mapped[datetime | None]  # low-importance memories lapse when unused
