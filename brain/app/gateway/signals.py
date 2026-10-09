"""Signal-protocol payloads (API.md §3.1). Unknown fields are rejected (extra="forbid" on the
envelope), so no event can carry a client user_id."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.gateway.envelope import Envelope

SignalId = Field(min_length=1, max_length=64)


class SignalPartial(Envelope):
    signal_id: str = SignalId
    text: str = Field(max_length=2000)


class SignalFinal(Envelope):
    signal_id: str = SignalId
    text: str = Field(min_length=1, max_length=2000)
    lang: str = Field(default="en", max_length=10)
    confidence: float | None = Field(default=None, ge=0, le=1)
    source: Literal["voice", "text", "schedule"] = "voice"
    utc_offset_min: int | None = Field(default=None, ge=-840, le=840)


class ToolError(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(max_length=40)
    message: str = Field(max_length=500)


class LocalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    said: str | None = Field(default=None, max_length=300)
    output: Any = None
    error: ToolError | None = None


class SignalHandledLocally(Envelope):
    signal_id: str = SignalId
    text: str = Field(min_length=1, max_length=2000)
    intent: str = Field(max_length=60)
    slots: dict[str, Any] = Field(default_factory=dict)
    result: LocalResult
    utc_offset_min: int | None = Field(default=None, ge=-840, le=840)


class SignalInterrupt(Envelope):
    signal_id: str | None = Field(default=None, max_length=64)


class ToolResult(Envelope):
    call_id: str = Field(min_length=1, max_length=64)
    ok: bool
    output: Any = None
    error: ToolError | None = None
    artifacts: list[Any] = Field(default_factory=list, max_length=20)


class SignalTrace(Envelope):
    """Device-measured spans in ms (§13): endpoint, stt_final, first_audio, …"""

    signal_id: str = SignalId
    spans: dict[str, float] = Field(max_length=20)
    stt_engine: str | None = Field(default=None, max_length=60)
    tts_engine: str | None = Field(default=None, max_length=60)


class EngineIncident(Envelope):
    role: Literal["stt", "tts", "wake", "vad", "local_llm", "tool"]
    engine: str = Field(max_length=60)
    error: str = Field(max_length=500)
    remedy: str = Field(max_length=40)
    outcome: Literal["recovered", "failed_explained", "degraded"] = "recovered"
