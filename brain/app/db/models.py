"""R0 tables (DATABASE.md §1, §2, §5). Every user-owned row has user_id; queries filter by it."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Identity,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, uuid7


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
