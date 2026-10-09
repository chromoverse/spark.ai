from __future__ import annotations

import json
import logging

import pytest
from pydantic import ValidationError

from app.core.logging import JsonFormatter, trace_id_var
from tests.conftest import Brain, make_settings


async def test_health_and_ready(brain: Brain) -> None:
    r = await brain.client.get("/health")
    assert r.json() == {"ok": True, "data": {"status": "up"}}
    assert r.headers["x-trace-id"]

    r = await brain.client.get("/ready")
    assert r.status_code == 200
    assert r.json()["data"] == {"db": "up", "redis": "up"}


async def test_unknown_route_uses_envelope(brain: Brain) -> None:
    r = await brain.client.get("/v2/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


async def test_cors_never_wildcard() -> None:
    with pytest.raises(ValidationError):
        make_settings(cors_origins="*")


async def test_weak_jwt_secret_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(jwt_secret="short")


def test_json_logs_carry_trace_and_redact_secrets() -> None:
    token = trace_id_var.set("t-123")
    try:
        record = logging.makeLogRecord(
            {
                "msg": "signed in",
                "levelname": "INFO",
                "name": "x",
                "refresh_token": "abc.def",
                "otp": "123456",
                "device": "d1",
            }
        )
        line = json.loads(JsonFormatter().format(record))
    finally:
        trace_id_var.reset(token)
    assert line["trace_id"] == "t-123"
    assert line["refresh_token"] == "[redacted]"
    assert line["otp"] == "[redacted]"
    assert line["device"] == "d1"
