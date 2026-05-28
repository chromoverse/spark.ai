"""Unit smoke tests for commerce/ — no browser, no network.

Covers:
  - receipt.save_receipt + envelope validation + safe-id sanitization
  - email.send_receipt_email returning structured failure (we don't
    actually hit Resend here; we monkey-patch its send)
  - watcher.start_receipt_watch timing out cleanly when the
    confirmation never appears (using a tiny dummy adapter)

The full Daraz e2e is in test_browser_daraz_e2e.py and requires a real
browser session.

Usage:
    python server/testing/test_commerce_units.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("SPARK_BROWSER_NOTIFICATIONS", "0")

from plugins.installed.web.browser.commerce import receipt as receipt_mod
from plugins.installed.web.browser.commerce import email as email_mod
from plugins.installed.web.browser.commerce.watcher import start_receipt_watch
from plugins.installed.web.browser.adapters.daraz import DarazAdapter, classify_checkout_page
from plugins.installed.web.browser.events import BrowserEventType, get_event_bus


# ── Test 1: receipt save round-trip ─────────────────────────────────────────

def test_receipt_save() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        rec = {
            "source": "daraz",
            "order_id": "ABC/123-test",   # contains an unsafe / char
            "total": 4999.0,
            "currency": "NPR",
            "source_url": "https://www.daraz.com.np/order/success/?tradeOrderId=ABC123",
            "items": [{"name": "Widget", "qty": 1, "price": "NPR 4999"}],
        }
        saved = receipt_mod.save_receipt(rec, base_dir=base)
        assert saved.receipt_path.exists(), "receipt.json not written"
        # Order id should be sanitized in the dir name (no slashes).
        assert "/" not in saved.dir.name, saved.dir.name
        assert "_" in saved.dir.name, saved.dir.name  # slash got replaced

        loaded = json.loads(saved.receipt_path.read_text(encoding="utf-8"))
        assert loaded["order_id"] == "ABC/123-test"  # original kept in JSON
        assert loaded["total"] == 4999.0
        # save_receipt should backfill captured_at if missing.
        assert "captured_at" in loaded


# ── Test 2: email send returns structured failure on error ─────────────────

def test_email_handles_resend_failure(monkeypatch) -> None:
    class _FakeBroken:
        @staticmethod
        def send(params):
            raise RuntimeError("resend api down")

    # Patch resend.Emails to a broken stub.
    monkeypatch.setattr(email_mod.resend, "Emails", _FakeBroken, raising=False)

    out = email_mod.send_receipt_email(
        {"source": "daraz", "order_id": "X1", "total": 100, "currency": "NPR",
         "source_url": "https://www.daraz.com.np/"},
        to_email="user@example.com",
        user_name="Test",
    )
    assert out["sent"] is False
    assert "resend api down" in (out["error"] or "")
    assert out["to"] == "user@example.com"


# ── Test 3: watcher times out cleanly when no confirmation arrives ──────────

class _DummyAdapter:
    name = "dummy"
    base_url = "https://example.test/"

    async def is_confirmation_page(self, page) -> bool:
        return False

    async def extract_receipt(self, page) -> dict:
        return {"source": "dummy"}


async def _run_watcher_timeout() -> None:
    captured_events: list = []
    bus = get_event_bus()
    for et in (BrowserEventType.RECEIPT_WATCH_STARTED,
               BrowserEventType.RECEIPT_WATCH_TIMEOUT):
        bus.subscribe(et, lambda e: captured_events.append(e))

    # Patch session.get_page to return a stub so the watcher loop runs.
    from plugins.installed.web.browser import session as session_mod

    class _StubPage:
        url = "https://example.test/somewhere"

    class _StubRuntime:
        async def find_or_create_page(self, _h):
            return _StubPage()

        async def bring_to_front(self, _p):
            return None

    class _StubSession:
        async def runtime(self):
            return _StubRuntime()

        async def get_page(self, host=None, *, focus=True):
            return _StubPage()

    original = session_mod._SESSION
    session_mod._SESSION = _StubSession()  # type: ignore[assignment]
    try:
        task = start_receipt_watch(
            _DummyAdapter(),
            timeout_s=2.0,
            poll_every_s=0.3,
            reminder_every_s=10.0,  # suppress reminders in this short test
        )
        result = await task
        assert result.timed_out is True, f"expected timeout, got {result}"
        assert result.captured is False
        # The watcher should have emitted START + TIMEOUT.
        types = [e.type for e in captured_events]
        assert BrowserEventType.RECEIPT_WATCH_STARTED in types, types
        assert BrowserEventType.RECEIPT_WATCH_TIMEOUT in types, types
    finally:
        session_mod._SESSION = original  # type: ignore[assignment]


# ── Test 4: Daraz shipping-ready stage detection ───────────────────────────

class _FakeLocator:
    def __init__(self, visible: bool):
        self._visible = visible

    @property
    def first(self):
        return self

    async def count(self) -> int:
        return 1 if self._visible else 0

    async def is_visible(self) -> bool:
        return self._visible


class _FakePage:
    def __init__(self, url: str, visible_selectors: set[str], text: str = ""):
        self.url = url
        self._visible_selectors = visible_selectors
        self._text = text

    def locator(self, selector: str) -> _FakeLocator:
        return _FakeLocator(selector in self._visible_selectors)

    async def evaluate(self, _script: str):
        return self._text


async def _run_daraz_stage_detection() -> None:
    page = _FakePage(
        "https://checkout.daraz.com.np/shipping?spm=test",
        {'button:has-text("Proceed to Pay")'},
    )
    stage = await classify_checkout_page(page)
    assert stage == "shipping_ready", stage

    page = _FakePage(
        "https://checkout.daraz.com.np/shipping?spm=test",
        set(),
    )
    stage = await classify_checkout_page(page)
    assert stage == "shipping", stage

    page = _FakePage(
        "https://payment.daraz.com.np/payment-cashier/checkout?tradeOrderId=20990501103260528",
        set(),
        text=(
            "Please have this amount ready on delivery day.\n"
            "To track the delivery of your order, go to My Account > My Order\n"
            "View Order\n"
            "We've sent you a confirmation email with the details of your order.\n"
            "Continue Shopping"
        ),
    )
    stage = await classify_checkout_page(page)
    assert stage == "success", stage
    assert await DarazAdapter().is_confirmation_page(page) is True


# ── Minimal runner (no pytest dep) ─────────────────────────────────────────

class _Monkeypatch:
    def __init__(self):
        self._undo: list = []

    def setattr(self, target, name, value, raising=True):
        had = hasattr(target, name)
        old = getattr(target, name, None)
        setattr(target, name, value)
        self._undo.append((target, name, old, had))

    def undo(self):
        for target, name, old, had in reversed(self._undo):
            if had:
                setattr(target, name, old)
            else:
                try:
                    delattr(target, name)
                except AttributeError:
                    pass


def main() -> int:
    failures: list[str] = []

    print("test_receipt_save ...", end=" ")
    try:
        test_receipt_save()
        print("OK")
    except Exception as e:
        print(f"FAIL: {e}")
        failures.append(f"test_receipt_save: {e}")

    print("test_email_handles_resend_failure ...", end=" ")
    mp = _Monkeypatch()
    try:
        test_email_handles_resend_failure(mp)
        print("OK")
    except Exception as e:
        print(f"FAIL: {e}")
        failures.append(f"test_email_handles_resend_failure: {e}")
    finally:
        mp.undo()

    print("test_watcher_timeout ...", end=" ")
    try:
        asyncio.run(_run_watcher_timeout())
        print("OK")
    except Exception as e:
        print(f"FAIL: {e}")
        failures.append(f"test_watcher_timeout: {e}")

    print("test_daraz_stage_detection ...", end=" ")
    try:
        asyncio.run(_run_daraz_stage_detection())
        print("OK")
    except Exception as e:
        print(f"FAIL: {e}")
        failures.append(f"test_daraz_stage_detection: {e}")

    if failures:
        print(f"\n[FAIL] {len(failures)} test(s) failed.")
        return 1
    print("\n[PASS] All commerce unit tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
