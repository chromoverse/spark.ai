"""X1: no route or socket event accepts a client-supplied user_id, and user A can't read or
change user B. Generated from the live route table (OpenAPI) and the gateway's event table, so
new routes and events are swept automatically. # proves §12, RULES §3"""

from __future__ import annotations

import re
import uuid
from typing import Any

import pytest

from app.gateway.server import EVENT_MODELS, ConnectAuth
from tests.conftest import Brain
from tests.fakes.device import FakeDevice

pytestmark = pytest.mark.scenario

# Routes reachable without an access token. Anything not listed must return 401 without one.
PUBLIC = {
    ("GET", "/health"),
    ("GET", "/ready"),
    ("POST", "/v2/auth/otp/start"),
    ("POST", "/v2/auth/otp/verify"),
    ("POST", "/v2/auth/refresh"),
    ("GET", "/v2/auth/google/start"),
    ("GET", "/v2/auth/google/callback"),
    ("POST", "/v2/auth/google/exchange"),
}
_PARAM = re.compile(r"\{[^}]+\}")


def _routes(brain: Brain) -> list[tuple[str, str]]:
    """The route table, read from OpenAPI (FastAPI's public view of every included router).
    A route hidden with include_in_schema=False would escape this sweep, so don't hide routes."""
    spec = brain.asgi.other_asgi_app.openapi()
    routes = sorted((m.upper(), p) for p, ops in spec["paths"].items() for m in ops)
    # Guard against a vacuous pass if the table ever comes back empty again.
    assert {
        ("GET", "/v2/me"),
        ("PATCH", "/v2/settings"),
        ("DELETE", "/v2/devices/{device_id}"),
    } <= set(routes)
    return routes


def _walk(schema: dict[str, Any], comps: dict[str, Any], where: str, seen: set[str]) -> None:
    """Fails if any model in the schema has a user_id field or accepts unknown fields."""
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        if name not in seen:
            seen.add(name)
            _walk(comps[name], comps, f"{where}→{name}", seen)
        return
    for key in ("anyOf", "allOf", "oneOf"):
        for sub in schema.get(key, []):
            _walk(sub, comps, where, seen)
    if "items" in schema:
        _walk(schema["items"], comps, where, seen)
    if props := schema.get("properties"):
        assert not any("user_id" in p.lower() for p in props), f"{where} has a user_id field"
        assert schema.get("additionalProperties") is False, f"{where} accepts unknown fields"
        for name, sub in props.items():
            _walk(sub, comps, f"{where}.{name}", seen)


async def test_x1_no_route_or_event_declares_user_id(brain: Brain) -> None:
    spec = brain.asgi.other_asgi_app.openapi()
    comps = spec.get("components", {}).get("schemas", {})
    for path, ops in spec["paths"].items():
        assert "user_id" not in path
        for method, op in ops.items():
            for param in op.get("parameters", []):
                assert "user_id" not in param["name"].lower(), f"{method} {path} ?{param['name']}"
            if body := op.get("requestBody"):
                schema = body["content"]["application/json"]["schema"]
                _walk(schema, comps, f"{method.upper()} {path}", set())

    for event, model in EVENT_MODELS.items() | {("connect", ConnectAuth)}:
        schema = model.model_json_schema()
        _walk(schema, schema.get("$defs", {}), event, set())

    # Every socket handler validates through EVENT_MODELS; nothing slips past the sweep.
    handlers = set(brain.rt.sio.handlers["/v2"])
    assert handlers - {"connect", "disconnect"} == set(EVENT_MODELS)


async def test_x1_private_routes_need_a_real_access_token(brain: Brain) -> None:
    routes = _routes(brain)
    assert set(PUBLIC) <= set(routes), "PUBLIC lists a route that no longer exists"
    tokens = await brain.sign_in()
    bad_headers: list[dict[str, str]] = [
        {},
        {"Authorization": "Bearer not-a-jwt"},
        {"Authorization": f"Bearer {tokens['refresh_token']}"},
        {"Authorization": f"Basic {tokens['access_token']}"},
    ]
    for method, path in routes:
        if (method, path) in PUBLIC:
            continue
        url = _PARAM.sub(str(uuid.uuid4()), path)
        for headers in bad_headers:
            r = await brain.client.request(method, url, json={}, headers=headers)
            assert r.status_code == 401, (method, path, headers, r.text)
            assert r.json()["error"]["code"] == "unauthorized"


async def test_x1_user_a_cannot_read_or_change_user_b(brain: Brain) -> None:
    a = await brain.sign_in("asha@example.com", "Asha's laptop")
    b = await brain.sign_in("ben@example.com", "Ben's laptop")
    b2 = await brain.sign_in("ben@example.com", "Ben's desktop")
    b_marks = {b["user"]["id"], "ben@example.com", b["device_id"], b2["device_id"], "Ben's"}
    spec = brain.asgi.other_asgi_app.openapi()
    has_body = {
        (m.upper(), p)
        for p, ops in spec["paths"].items()
        for m, op in ops.items()
        if "requestBody" in op
    }
    as_a = brain.auth(a)
    deferred: list[tuple[str, str]] = []

    for method, path in _routes(brain):
        if (method, path) in PUBLIC:
            continue
        if _PARAM.search(path):
            # B's resource ids with A's token: never found, never touched.
            for b_id in (b["device_id"], b2["device_id"]):
                url = _PARAM.sub(b_id, path)
                r = await brain.client.request(method, url, json={}, headers=as_a)
                assert r.status_code == 404, (method, path, r.text)
        elif (method, path) in has_body:
            r = await brain.client.request(
                method, path, json={"user_id": b["user"]["id"]}, headers=as_a
            )
            assert r.status_code == 422, (method, path, r.text)
        elif method == "GET":
            r = await brain.client.get(path, params={"user_id": b["user"]["id"]}, headers=as_a)
            assert r.status_code == 200, (method, path)
            assert not any(mark in r.text for mark in b_marks), (method, path)
        else:
            deferred.append((method, path))  # body-less actions (logout): run last

    for method, path in deferred:
        r = await brain.client.request(
            method, path, json={"user_id": b["user"]["id"]}, headers=as_a
        )
        assert r.status_code == 200, (method, path)

    # B is untouched: both devices, settings, and live sessions.
    as_b = brain.auth(b2)
    r = await brain.client.get("/v2/devices", headers=as_b)
    assert len(r.json()["data"]["items"]) == 2
    assert (await brain.client.get("/v2/settings", headers=as_b)).json()["data"]["verbosity"] == (
        "normal"
    )
    r = await brain.client.post("/v2/auth/refresh", json={"refresh_token": b["refresh_token"]})
    assert r.status_code == 200


async def test_x1_socket_events_reject_user_id(brain: Brain) -> None:
    a = await brain.sign_in("asha@example.com")
    b = await brain.sign_in("ben@example.com")
    device = FakeDevice(brain.url, a)
    await device.connect()
    try:
        for event in EVENT_MODELS:
            ack = await device.call(event, {"user_id": b["user"]["id"]})
            assert ack["ok"] is False and ack["error"]["code"] == "invalid_input", event
    finally:
        await device.close()
