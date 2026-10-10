"""The tool contract (REDESIGN §7.1, §20.1, CODING_STANDARDS §2). Device tools are declared here and
run on a body; brain tools run in the agent loop. Permission rules match on one input field
(`match`); MCP annotations count only for trusted servers (§20.4)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel

from app.llm.types import ToolDef

DEVICE_FIELD = "device"  # optional target on every device tool (§26.3); stripped before sending


class ToolError(Exception):
    """A brain tool failed in a way the model can act on (API.md §3.3): `message` says how."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class Risk(StrEnum):
    READ = "read"
    WRITE = "write"  # reversible
    DESTRUCTIVE = "destructive"
    EXTERNAL = "external"  # sends, posts, or buys: touches other people or money


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
    output_model: type[BaseModel] | None = None
    match: str | None = None  # input field permission patterns match, e.g. "path", "command"
    review: bool = False  # medium risk: the auto-reviewer checks it in default mode (§20.6)
    confirm: str = ""  # what an approval says, e.g. "delete {path}"
    keywords: str = ""  # extra words for the agent's tool preselector
    mcp_server: str | None = None
    mcp_trusted: bool = False
    annotations: Mapping[str, bool] = field(default_factory=dict)  # MCP hints (readOnlyHint, …)
    # Brain tools outside the loop (integrations, R4): (hooks.Call, input) → output.
    handler: Callable[[Any, dict[str, Any]], Awaitable[Any]] | None = None

    def to_def(self, *, with_device: bool = False) -> ToolDef:
        schema = self.input_model.model_json_schema()
        schema.pop("title", None)
        schema["additionalProperties"] = False
        if with_device and self.target == "device":
            props = dict(schema.get("properties", {}))
            props[DEVICE_FIELD] = {
                "type": "string",
                "description": "Device to run it on, by name or kind ('phone', 'Laptop'). "
                "Omit for the device the user is talking to.",
            }
            schema["properties"] = props
        return ToolDef(self.name, self.description, schema)

    def validate(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Raises pydantic.ValidationError; returns the normalized input sent to the device."""
        return self.input_model.model_validate(raw).model_dump(exclude_none=True)

    def check_output(self, output: Any) -> Any:
        """API.md §3.3: a device result must match the declared output (raises ValidationError)."""
        if self.output_model is None or output is None:
            return output
        return self.output_model.model_validate(output).model_dump(exclude_none=True)

    def matched(self, inp: dict[str, Any]) -> str:
        """The value permission patterns are matched against ('' when the tool has none)."""
        if self.match is None:
            return ""
        value = str(inp.get(self.match, ""))
        return value.replace("\\", "/") if self.match == "path" else value

    def describe(self, inp: dict[str, Any]) -> str:
        """One line for approvals: 'delete C:/Users/asha/Downloads'."""
        try:
            return self.confirm.format(**inp) if self.confirm else f"run {self.name}"
        except (KeyError, IndexError):
            return f"run {self.name}"
