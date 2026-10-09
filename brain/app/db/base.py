from __future__ import annotations

import os
import time
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uuid7() -> uuid.UUID:
    """RFC 9562 UUIDv7: 48-bit ms timestamp + random. Stdlib gets uuid7 only in 3.14."""
    ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")
    value = (ms & (2**48 - 1)) << 80
    value |= 0x7 << 76 | (rand & 0xFFF) << 64
    value |= 0b10 << 62 | (rand >> 12) & (2**62 - 1)
    return uuid.UUID(int=value)


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_N_name)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )
    type_annotation_map = {
        datetime: DateTime(timezone=True),
        dict[str, Any]: JSONB,
        list[Any]: JSONB,
        list[str]: ARRAY(Text),
    }


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
