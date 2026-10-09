from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Envelope(BaseModel):
    """Fields every device → brain event carries."""

    model_config = ConfigDict(extra="forbid")
    v: Literal[2]
    id: str = Field(min_length=1, max_length=64)
    ts: int  # epoch ms on the device
    trace_id: str | None = Field(default=None, max_length=64)
