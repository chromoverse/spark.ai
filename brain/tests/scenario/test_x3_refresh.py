"""X3: refresh-token reuse revokes the session. # proves §12 (auth)"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models import AuditLog, Session
from tests.conftest import Brain

pytestmark = pytest.mark.scenario


async def _refresh(brain: Brain, token: str) -> tuple[int, dict]:  # type: ignore[type-arg]
    r = await brain.client.post("/v2/auth/refresh", json={"refresh_token": token})
    return r.status_code, r.json()


async def test_x3_refresh_reuse_revokes_session(brain: Brain) -> None:
    first = await brain.sign_in()
    status, body = await _refresh(brain, first["refresh_token"])
    assert status == 200
    second = body["data"]
    assert second["refresh_token"] != first["refresh_token"]
    assert second["device_id"] == first["device_id"]

    # The stolen (old) token is replayed: the whole session dies, including the fresh token.
    status, body = await _refresh(brain, first["refresh_token"])
    assert status == 401 and body["error"]["code"] == "unauthorized"
    assert (await _refresh(brain, second["refresh_token"]))[0] == 401
    r = await brain.client.get("/v2/me", headers=brain.auth(second))
    assert r.status_code == 401

    async with brain.rt.db() as db:
        session = await db.scalar(select(Session))
        actions = (await db.scalars(select(AuditLog.action))).all()
    assert session is not None and session.revoked_at is not None
    assert "refresh_reuse" in actions


async def test_refresh_is_bound_to_its_session(brain: Brain) -> None:
    a = await brain.sign_in("asha@example.com")
    b = await brain.sign_in("ben@example.com")
    sid_a = a["refresh_token"].split(".")[0]
    secret_b = b["refresh_token"].split(".")[1]
    assert (await _refresh(brain, f"{sid_a}.{secret_b}"))[0] == 401
    assert (await _refresh(brain, "garbage-token-value"))[0] == 401


async def test_access_token_lasts_15_minutes(brain: Brain) -> None:
    tokens = await brain.sign_in()
    assert tokens["access_expires_in"] == 900
    assert (await brain.client.get("/v2/me", headers=brain.auth(tokens))).status_code == 200
    brain.clock.advance(15 * 60)
    r = await brain.client.get("/v2/me", headers=brain.auth(tokens))
    assert r.status_code == 401
    assert r.json()["error"]["message"] == "You've been signed out. Sign in again and we're good."
    status, body = await _refresh(brain, tokens["refresh_token"])
    assert status == 200
    assert (await brain.client.get("/v2/me", headers=brain.auth(body["data"]))).status_code == 200


async def test_logout_ends_the_session(brain: Brain) -> None:
    tokens = await brain.sign_in()
    r = await brain.client.post("/v2/auth/logout", headers=brain.auth(tokens))
    assert r.status_code == 200
    assert (await brain.client.get("/v2/me", headers=brain.auth(tokens))).status_code == 401
    assert (await _refresh(brain, tokens["refresh_token"]))[0] == 401


async def test_me_returns_profile_and_default_settings(brain: Brain) -> None:
    tokens = await brain.sign_in("Asha@Example.com")
    r = await brain.client.get("/v2/me", headers=brain.auth(tokens))
    data = r.json()["data"]
    assert data["user"]["email"] == "asha@example.com"
    assert data["device_id"] == tokens["device_id"]
    assert data["settings"]["language"] == "en"
    assert data["settings"]["permission_mode"] == "default"
