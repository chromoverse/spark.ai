"""X2: OTP hashed at rest; locked after 5 wrong tries. # proves §12 (auth)"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text

from app.db.models import OtpCode
from tests.conftest import Brain

pytestmark = pytest.mark.scenario

EMAIL = "asha@example.com"
DEVICE = {"name": "Laptop"}


async def _start(brain: Brain, email: str = EMAIL) -> str:
    r = await brain.client.post("/v2/auth/otp/start", json={"email": email})
    assert r.status_code == 200, r.text
    return brain.resend.last_code(email)


async def _verify(brain: Brain, code: str, email: str = EMAIL) -> tuple[int, dict]:  # type: ignore[type-arg]
    r = await brain.client.post(
        "/v2/auth/otp/verify", json={"email": email, "code": code, "device": DEVICE}
    )
    return r.status_code, r.json()


async def test_x2_otp_stored_only_as_hash(brain: Brain) -> None:
    code = await _start(brain)
    async with brain.rt.db() as db:
        row = await db.scalar(select(OtpCode))
        dump = (await db.execute(text("select row_to_json(o)::text from otp_codes o"))).scalar()
    assert row is not None and row.code_hash != code and len(row.code_hash) == 64
    assert code not in str(dump)


async def test_x2_sixth_wrong_attempt_is_locked(brain: Brain) -> None:
    code = await _start(brain)
    wrong = "000000" if code != "000000" else "111111"
    results = [await _verify(brain, wrong) for _ in range(5)]
    assert [s for s, _ in results] == [401] * 5
    assert results[0][1]["error"]["message"] == "That code didn't match. 4 tries left."
    assert "last try" in results[4][1]["error"]["message"]

    status, body = await _verify(brain, code)  # 6th try, even with the right code
    assert status == 429 and body["error"]["code"] == "rate_limited"
    assert "fresh one" in body["error"]["message"]

    brain.clock.advance(61)
    status, body = await _verify(brain, await _start(brain))
    assert status == 200 and body["data"]["refresh_token"]


async def test_otp_cooldown_60s(brain: Brain) -> None:
    await _start(brain)
    r = await brain.client.post("/v2/auth/otp/start", json={"email": EMAIL})
    assert r.status_code == 429
    assert 0 < r.json()["error"]["retry_after_s"] <= 61
    brain.clock.advance(61)
    await _start(brain)


async def test_otp_expires_after_10_minutes(brain: Brain) -> None:
    code = await _start(brain)
    brain.clock.advance(601)
    status, body = await _verify(brain, code)
    assert status == 401 and "expired" in body["error"]["message"]


async def test_otp_is_single_use(brain: Brain) -> None:
    code = await _start(brain)
    assert (await _verify(brain, code))[0] == 200
    assert (await _verify(brain, code))[0] == 401


async def test_otp_mail_outage_is_explained_and_leaves_no_cooldown(brain: Brain) -> None:
    brain.resend.fail_status = 500
    r = await brain.client.post("/v2/auth/otp/start", json={"email": EMAIL})
    assert r.status_code == 503
    assert r.json()["error"] == {
        "code": "provider_unavailable",
        "message": "Couldn't send the code just now. Try again in a minute.",
        "retry_after_s": 30,
    }
    brain.resend.fail_status = None
    await _start(brain)  # no cooldown from the failed attempt


async def test_otp_bad_email_and_extra_fields_rejected(brain: Brain) -> None:
    r = await brain.client.post("/v2/auth/otp/start", json={"email": "not-an-email"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_input"
    r = await brain.client.post(
        "/v2/auth/otp/start", json={"email": EMAIL, "user_id": "someone-else"}
    )
    assert r.status_code == 422
