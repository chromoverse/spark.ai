from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Iterable, Optional
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)


class CloudflareKVCircuitOpenError(RuntimeError):
    """Raised when the circuit breaker is open for Cloudflare KV calls."""


class CloudflareKVManager:
    BASE_URL = "https://api.cloudflare.com/client/v4"
    _GLOBAL_KEY_PATTERN = re.compile(r"^[A-Fa-f0-9]{37}$")
    _BULK_GET_MAX_KEYS = 100
    _LIST_KEYS_MIN_LIMIT = 10

    def __init__(
        self,
        *,
        api_token: str,
        api_email: str = "",
        account_id: str,
        namespace_id: str,
        timeout_ms: int = 3000,
        max_retries: int = 3,
        circuit_failure_threshold: int = 3,
        circuit_cooldown_s: int = 30,
    ) -> None:
        self.api_token = self._normalize_token(api_token)
        self.api_email = (api_email or "").strip()
        self.account_id = account_id
        self.namespace_id = namespace_id
        if not self.api_token:
            raise ValueError("Cloudflare API token is empty")
        self.timeout_s = max(0.2, float(timeout_ms) / 1000.0)
        self.max_retries = max(1, int(max_retries))
        self.circuit_failure_threshold = max(1, int(circuit_failure_threshold))
        self.circuit_cooldown_s = max(1, int(circuit_cooldown_s))

        self._client = httpx.AsyncClient(timeout=self.timeout_s)
        self._failures = 0
        self._circuit_open_until = 0.0

    @staticmethod
    def _normalize_token(token: str) -> str:
        """
        Accept either raw token or strings accidentally prefixed with `Bearer `.
        """
        normalized = (token or "").strip()
        if normalized.lower().startswith("bearer "):
            normalized = normalized[7:].strip()
        return normalized

    async def close(self) -> None:
        await self._client.aclose()

    @property
    def namespace_base(self) -> str:
        return (
            f"/accounts/{self.account_id}/storage/kv/namespaces/{self.namespace_id}"
        )

    def _headers(self) -> dict[str, str]:
        if self._use_global_key_auth():
            return {
                "X-Auth-Key": self.api_token,
                "X-Auth-Email": self.api_email,
                "Content-Type": "application/json",
            }
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

    def _use_global_key_auth(self) -> bool:
        """
        Use global-key auth only when email is present and token matches global-key shape.
        This prevents accidental mode switch when a bearer API token is used with an email env var.
        """
        token = (self.api_token or "").strip()
        email = (self.api_email or "").strip()
        return bool(email and self._GLOBAL_KEY_PATTERN.fullmatch(token))

    @property
    def auth_mode(self) -> str:
        return "global_api_key" if self._use_global_key_auth() else "api_token"

    async def validate_auth(self) -> None:
        """
        Validate Cloudflare credentials and ensure token/key can see the configured account.
        Raises RuntimeError with actionable reason if invalid.
        """
        if self._use_global_key_auth():
            response = await self._request(
                "GET",
                "/user",
                expect_json=True,
            )
            payload = response.json()
            if not bool(payload.get("success", False)):
                raise RuntimeError("Cloudflare global key auth failed")
            return

        verify = await self._request(
            "GET",
            "/user/tokens/verify",
            expect_json=True,
        )
        verify_payload = verify.json()
        if not bool(verify_payload.get("success", False)):
            raise RuntimeError("Cloudflare API token verify failed")
        token_status = str((verify_payload.get("result") or {}).get("status", "")).lower()
        if token_status and token_status != "active":
            raise RuntimeError(f"Cloudflare API token is not active (status={token_status})")

        accounts = await self._request(
            "GET",
            "/accounts",
            expect_json=True,
        )
        accounts_payload = accounts.json()
        result = accounts_payload.get("result", [])
        if not isinstance(result, list):
            result = []
        visible_ids = {str(item.get("id", "")).strip() for item in result if isinstance(item, dict)}
        if self.account_id not in visible_ids:
            raise RuntimeError(
                "Cloudflare API token is valid but has no access to configured account_id. "
                "Grant account resource access and KV permissions."
            )

    def _assert_circuit(self) -> None:
        now = time.time()
        if now < self._circuit_open_until:
            raise CloudflareKVCircuitOpenError(
                f"Cloudflare KV circuit open for {self._circuit_open_until - now:.1f}s"
            )

    def _record_success(self) -> None:
        self._failures = 0
        self._circuit_open_until = 0.0

    def _record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.circuit_failure_threshold:
            self._circuit_open_until = time.time() + self.circuit_cooldown_s
            logger.warning(
                "Cloudflare KV circuit opened for %ss after %s consecutive failures",
                self.circuit_cooldown_s,
                self._failures,
            )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        expect_json: bool = True,
        ignored_status_codes: Optional[set[int]] = None,
        **kwargs: Any,
    ) -> httpx.Response:
        self._assert_circuit()
        headers = self._headers()
        custom_headers = kwargs.pop("headers", None)
        if isinstance(custom_headers, dict):
            headers.update(custom_headers)
        if not (
            ("Authorization" in headers and str(headers.get("Authorization", "")).strip())
            or (
                str(headers.get("X-Auth-Key", "")).strip()
                and str(headers.get("X-Auth-Email", "")).strip()
            )
        ):
            raise RuntimeError("Cloudflare request missing auth headers")
        url = f"{self.BASE_URL}{path}"
        ignored = ignored_status_codes or set()

        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = await self._client.request(method, url, headers=headers, **kwargs)
                if response.status_code in ignored:
                    # Expected miss paths (for example, KV GET 404) should not trip circuit breaker.
                    self._record_success()
                    return response
                if response.status_code in (429, 500, 502, 503, 504):
                    if attempt < (self.max_retries - 1):
                        await asyncio.sleep(min(2.0, 0.2 * (2 ** attempt)))
                        continue
                if response.status_code >= 400:
                    self._record_failure()
                    response.raise_for_status()
                self._record_success()
                if expect_json and response.content:
                    _ = response.json()
                return response
            except CloudflareKVCircuitOpenError:
                raise
            except Exception as exc:
                last_exc = exc
                if attempt < (self.max_retries - 1):
                    await asyncio.sleep(min(2.0, 0.2 * (2 ** attempt)))
                    continue
                self._record_failure()
        if last_exc:
            raise last_exc
        raise RuntimeError("Cloudflare KV request failed with unknown error")

    async def ping(self) -> bool:
        try:
            await self.scan_prefix(prefix="", cursor=None, limit=self._LIST_KEYS_MIN_LIMIT)
            return True
        except Exception:
            return False

    async def get(self, key: str) -> Optional[str]:
        encoded = quote(key, safe="")
        try:
            response = await self._request(
                "GET",
                f"{self.namespace_base}/values/{encoded}",
                expect_json=False,
                ignored_status_codes={404},
            )
            if response.status_code == 404:
                return None
            text = response.text
            return text if text != "" else None
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return None
            raise

    async def set(self, key: str, value: str, ex: Optional[int] = None) -> bool:
        encoded = quote(key, safe="")
        params: dict[str, Any] = {}
        if ex is not None:
            params["expiration_ttl"] = int(ex)
        await self._request(
            "PUT",
            f"{self.namespace_base}/values/{encoded}",
            expect_json=False,
            params=params,
            content=value.encode("utf-8"),
            headers=(
                {
                    "X-Auth-Key": self.api_token,
                    "X-Auth-Email": self.api_email,
                    "Content-Type": "text/plain; charset=utf-8",
                }
                if self._use_global_key_auth()
                else {
                    "Authorization": f"Bearer {self.api_token}",
                    "Content-Type": "text/plain; charset=utf-8",
                }
            ),
        )
        return True

    async def delete(self, *keys: str) -> bool:
        if not keys:
            return True
        for key in keys:
            encoded = quote(key, safe="")
            try:
                await self._request(
                    "DELETE",
                    f"{self.namespace_base}/values/{encoded}",
                    expect_json=False,
                    ignored_status_codes={404},
                )
            except httpx.HTTPStatusError as exc:
                if exc.response is not None and exc.response.status_code == 404:
                    continue
                raise
        return True

    async def scan_prefix(
        self,
        *,
        prefix: str,
        cursor: Optional[str] = None,
        limit: int = 1000,
    ) -> tuple[Optional[str], list[str]]:
        effective_limit = max(self._LIST_KEYS_MIN_LIMIT, min(1000, int(limit)))
        params: dict[str, Any] = {
            "prefix": prefix,
            "limit": effective_limit,
        }
        if cursor:
            params["cursor"] = cursor
        response = await self._request(
            "GET",
            f"{self.namespace_base}/keys",
            params=params,
            expect_json=True,
        )
        payload = response.json()
        result = payload.get("result", [])
        keys = [str(item.get("name", "")) for item in result if item.get("name")]
        info = payload.get("result_info", {}) or {}
        next_cursor = info.get("cursor")
        if isinstance(next_cursor, str) and next_cursor.strip():
            return next_cursor, keys
        return None, keys

    async def bulk_set(self, items: list[tuple[str, str, Optional[int]]]) -> bool:
        if not items:
            return True
        payload: list[dict[str, Any]] = []
        for key, value, ex in items:
            item: dict[str, Any] = {"key": key, "value": value}
            if ex is not None:
                item["expiration_ttl"] = int(ex)
            payload.append(item)
        await self._request(
            "PUT",
            f"{self.namespace_base}/bulk",
            json=payload,
            expect_json=True,
        )
        return True

    async def bulk_get(self, keys: list[str]) -> list[Optional[str]]:
        if not keys:
            return []

        response_map: dict[str, Optional[str]] = {}
        bulk_error: Exception | None = None

        # Official endpoint: POST /bulk/get with up to 100 keys per request.
        for i in range(0, len(keys), self._BULK_GET_MAX_KEYS):
            chunk = keys[i : i + self._BULK_GET_MAX_KEYS]
            try:
                response = await self._request(
                    "POST",
                    f"{self.namespace_base}/bulk/get",
                    json={"keys": chunk},
                    expect_json=True,
                )
                payload = response.json()
                result = payload.get("result", {})
                values_obj: Any = result.get("values") if isinstance(result, dict) else {}

                if isinstance(values_obj, dict):
                    for key, value in values_obj.items():
                        response_map[str(key)] = None if value is None else str(value)
                    continue

                # Fallback shape handling for API variations.
                if isinstance(result, dict):
                    for key, value in result.items():
                        if key == "values":
                            continue
                        response_map[str(key)] = None if value is None else str(value)
                    continue
                if isinstance(result, list):
                    for item in result:
                        if not isinstance(item, dict):
                            continue
                        key = str(item.get("name") or item.get("key") or "")
                        if not key:
                            continue
                        value = item.get("value")
                        response_map[key] = None if value is None else str(value)
                    continue
            except Exception as exc:
                bulk_error = exc
                break

        if not response_map and bulk_error is not None:
            logger.debug("Cloudflare KV bulk_get endpoint failed, falling back to individual gets: %s", bulk_error)

        if response_map:
            return [response_map.get(key) for key in keys]

        values = await asyncio.gather(*(self.get(key) for key in keys), return_exceptions=True)
        final_values: list[Optional[str]] = []
        for value in values:
            if isinstance(value, BaseException) or value is None:
                final_values.append(None)
            else:
                final_values.append(str(value))
        return final_values

    async def rpush(self, key: str, *values: str) -> bool:
        if not values:
            return True
        current = await self.get(key)
        items: list[str] = []
        if current:
            try:
                parsed = json.loads(current)
                if isinstance(parsed, list):
                    items = [str(v) for v in parsed]
            except json.JSONDecodeError:
                items = []
        items.extend([str(v) for v in values])
        if key.startswith("kernel:recent:"):
            items = items[-500:]
        await self.set(key, json.dumps(items, ensure_ascii=False))
        return True

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        current = await self.get(key)
        if not current:
            return []
        try:
            parsed = json.loads(current)
            if not isinstance(parsed, list):
                return []
            values = [str(v) for v in parsed]
            n = len(values)
            if n == 0:
                return []

            s = start if start >= 0 else n + start
            e = end if end >= 0 else n + end
            s = max(0, s)
            e = min(n - 1, e)
            if s > e:
                return []
            return values[s : e + 1]
        except json.JSONDecodeError:
            return []
