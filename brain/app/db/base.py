from __future__ import annotations

import os
import time
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql.base import ischema_names
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import UserDefinedType


class HalfVec(UserDefinedType[list[float]]):
    """pgvector's `halfvec(n)`: 16-bit floats, half the row of `vector(n)` (768 bytes at 384
    dims) for the same ranking. Values travel in text form ('[0.1,0.2]'); nothing reads
    embeddings back, the database compares them."""

    cache_ok = True

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def get_col_spec(self, **kw: Any) -> str:
        return f"halfvec({self.dim})"

    def bind_processor(self, dialect: Any) -> Any:
        def process(value: list[float] | str | None) -> str | None:
            if value is None or isinstance(value, str):
                return value
            return "[" + ",".join(f"{x:.6f}" for x in value) + "]"

        return process


ischema_names["halfvec"] = HalfVec  # reflection (the migration test) knows the type


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
