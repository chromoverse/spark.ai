from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import jwt

from tests.fakes.clock import FakeClock


class FakeGoogle:
    """Google's authorize screen + token endpoint. `authorize()` plays the user clicking their
    account; `handle()` serves oauth2.googleapis.com/token for the brain's http client."""

    def __init__(self, clock: FakeClock, client_id: str, client_secret: str) -> None:
        self.clock = clock
        self.client_id = client_id
        self.client_secret = client_secret
        self.grants: dict[str, dict[str, Any]] = {}
        self.claim_overrides: dict[str, Any] = {}
        self.token_status: int | None = None

    def authorize(
        self,
        location: str,
        *,
        sub: str = "google-sub-1",
        email: str = "asha@gmail.com",
        name: str = "Asha",
        email_verified: bool = True,
    ) -> dict[str, str]:
        url = urlparse(location)
        assert f"{url.scheme}://{url.netloc}{url.path}" == (
            "https://accounts.google.com/o/oauth2/v2/auth"
        )
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        assert q["client_id"] == self.client_id and q["response_type"] == "code"
        assert set(q["scope"].split()) == {"openid", "email", "profile"}
        code = secrets.token_urlsafe(16)
        self.grants[code] = {
            "redirect_uri": q["redirect_uri"],
            "claims": {
                "iss": "https://accounts.google.com",
                "aud": self.client_id,
                "sub": sub,
                "email": email,
                "email_verified": email_verified,
                "name": name,
                "nonce": q["nonce"],
            },
        }
        return {"code": code, "state": q["state"]}

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/token" and request.method == "POST"
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        if self.token_status:
            return httpx.Response(self.token_status, json={"error": "server_error"})
        grant = self.grants.pop(form.get("code", ""), None)
        if (
            grant is None
            or form.get("client_secret") != self.client_secret
            or form.get("grant_type") != "authorization_code"
            or form.get("redirect_uri") != grant["redirect_uri"]
        ):
            return httpx.Response(400, json={"error": "invalid_grant"})
        now = int(self.clock.now().timestamp())
        claims = grant["claims"] | {"iat": now, "exp": now + 3600} | self.claim_overrides
        id_token = jwt.encode(claims, "fake-google-signing-key-" + "k" * 32, algorithm="HS256")
        return httpx.Response(
            200, json={"id_token": id_token, "access_token": "ya29.fake", "token_type": "Bearer"}
        )
