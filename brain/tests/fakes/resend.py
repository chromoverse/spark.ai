from __future__ import annotations

import json
import re
from typing import Any

import httpx


class FakeResend:
    """Captures OTP emails instead of sending them. Set `fail_status` to simulate an outage."""

    def __init__(self) -> None:
        self.outbox: list[dict[str, Any]] = []
        self.fail_status: int | None = None

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/emails"
        assert request.headers["authorization"].startswith("Bearer ")
        if self.fail_status:
            return httpx.Response(self.fail_status, json={"message": "fake outage"})
        self.outbox.append(json.loads(request.content))
        return httpx.Response(200, json={"id": f"fake-{len(self.outbox)}"})

    def last_code(self, email: str) -> str:
        for mail in reversed(self.outbox):
            if mail["to"] == [email.strip().lower()]:
                match = re.search(r"\b(\d{6})\b", mail["text"])
                assert match
                return match.group(1)
        raise AssertionError(f"no code mailed to {email}")
