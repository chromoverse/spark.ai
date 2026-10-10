from __future__ import annotations


class ToolFailure(Exception):
    """A device tool failed in a way the model can act on (API.md §3.3)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class Unsupported(Exception):
    """This device can't do it (wrong OS, missing hardware); the message says so plainly."""
