"""The tool contract (REDESIGN §7.1, CODING_STANDARDS §2). R1 carries what the reflex needs; the
permission engine, annotations, and output schemas join with the agent loop in R2."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel

from app.llm.types import ToolDef


class Risk(StrEnum):
    READ = "read"
    WRITE = "write"  # reversible
    DESTRUCTIVE = "destructive"
    EXTERNAL = "external"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    target: Literal["brain", "device"]
    risk: Risk
    parallel_safe: bool = True
    requires: frozenset[str] = field(default_factory=frozenset)
    timeout_s: float = 5.0

    def to_def(self) -> ToolDef:
        schema = self.input_model.model_json_schema()
        schema.pop("title", None)
        schema["additionalProperties"] = False
        return ToolDef(self.name, self.description, schema)

    def validate(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Raises pydantic.ValidationError; returns the normalized input sent to the device."""
        return self.input_model.model_validate(raw).model_dump(exclude_none=True)
