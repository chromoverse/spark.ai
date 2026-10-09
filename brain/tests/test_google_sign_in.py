"""Google sign-in for the desktop: OIDC + loopback redirect + PKCE (API.md §2.1)."""

from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.core.security import pkce_s256
from tests.conftest import Brain
from tests.fakes.google import FakeGoogle

PORT = 53682


def _google(brain: Brain) -> FakeGoogle:
    assert brain.google is not None
    return brain.google


async def _to_loopback(brain: Brain, verifier: str, **user: Any) -> dict[str, str]:
    """Runs start → Google → callback and returns the query the desktop's listener receives."""
    r = await brain.client.get(
        "/v2/auth/google/start",
        params={
            "device_name": "Laptop",
            "platform": "win32",
            "port": PORT,
            "code_challenge": pkce_s256(verifier),
        },
    )
    assert r.status_code == 302, r.text
    grant = _google(brain).authorize(r.headers["location"], **user)
    r = await brain.client.get("/v2/auth/google/callback", params=grant)
    assert r.status_code == 302, r.text
    url = urlparse(r.headers["location"])
    assert (url.scheme, url.hostname, url.port, url.path) == (
        "http",
        "127.0.0.1",
        PORT,
        "/callback",
    )
    return {k: v[0] for k, v in parse_qs(url.query).items()}


async def _exchange(brain: Brain, code: str, verifier: str) -> tuple[int, dict[str, Any]]:
    r = await brain.client.post(
        "/v2/auth/google/exchange", json={"code": code, "code_verifier": verifier}
    )
    return r.status_code, r.json()


async def test_google_sign_in_end_to_end(brain: Brain) -> None:
    verifier = secrets.token_urlsafe(48)
    q = await _to_loopback(brain, verifier)
    status, body = await _exchange(brain, q["code"], verifier)
    assert status == 200, body
    tokens = body["data"]
    assert tokens["user"] == {"id": tokens["user"]["id"], "email": "asha@gmail.com", "name": "Asha"}
    me = await brain.client.get("/v2/me", headers=brain.auth(tokens))
    assert me.json()["data"]["device_id"] == tokens["device_id"]

    # One-time: the same login code can't be exchanged twice.
    assert (await _exchange(brain, q["code"], verifier))[0] == 401


async def test_login_code_needs_the_matching_verifier(brain: Brain) -> None:
    verifier = secrets.token_urlsafe(48)
    q = await _to_loopback(brain, verifier)
    status, body = await _exchange(brain, q["code"], secrets.token_urlsafe(48))
    assert status == 401 and body["error"]["code"] == "unauthorized"
    assert (await _exchange(brain, q["code"], verifier))[0] == 401  # burned by the bad try


async def test_google_links_to_existing_email_account(brain: Brain) -> None:
    otp_tokens = await brain.sign_in("asha@gmail.com")
    verifier = secrets.token_urlsafe(48)
    q = await _to_loopback(brain, verifier, email="Asha@gmail.com")
    _, body = await _exchange(brain, q["code"], verifier)
    assert body["data"]["user"]["id"] == otp_tokens["user"]["id"]


async def test_unknown_state_shows_a_friendly_page(brain: Brain) -> None:
    r = await brain.client.get("/v2/auth/google/callback", params={"code": "x", "state": "nope"})
    assert r.status_code == 400
    assert "expired" in r.text and "Traceback" not in r.text


async def test_user_cancel_and_bad_tokens_reach_the_app(brain: Brain) -> None:
    verifier = secrets.token_urlsafe(48)
    r = await brain.client.get(
        "/v2/auth/google/start",
        params={"device_name": "Laptop", "port": PORT, "code_challenge": pkce_s256(verifier)},
    )
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    r = await brain.client.get(
        "/v2/auth/google/callback", params={"error": "access_denied", "state": state}
    )
    assert parse_qs(urlparse(r.headers["location"]).query) == {"error": ["cancelled"]}

    for override in ({"nonce": "forged"}, {"aud": "someone-else"}, {"email_verified": False}):
        _google(brain).claim_overrides = override
        q = await _to_loopback(brain, verifier)
        assert q == {"error": "failed"}, override
    _google(brain).claim_overrides = {}


async def test_start_validates_the_handoff_params(brain: Brain) -> None:
    base = {"device_name": "Laptop", "port": PORT, "code_challenge": "short"}
    assert (await brain.client.get("/v2/auth/google/start", params=base)).status_code == 422
    good = base | {"code_challenge": pkce_s256(secrets.token_urlsafe(48))}
    for bad in ({"port": 80}, {"user_id": "x"}):
        r = await brain.client.get("/v2/auth/google/start", params=good | bad)
        assert r.status_code == 422, bad
