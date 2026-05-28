"""Unit smoke tests for the Booking.com browser adapter.

No browser, no network. This covers the parts that should stay stable:
date/guest parameter plumbing, stage classification, and confirmation
extraction from a Booking.com-style confirmation page.

Usage:
    python server/testing/test_booking_units.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from plugins.installed.web.browser.adapters.booking import (
    BookingAdapter,
    _search_url,
    _with_booking_params,
    classify_checkout_page,
)


class _FakePage:
    def __init__(self, url: str, text: str = "", title: str = "Booking.com"):
        self.url = url
        self._text = text
        self._title = title

    async def evaluate(self, _script: str):
        return self._text

    async def title(self) -> str:
        return self._title


def test_booking_search_url() -> None:
    ctx = {
        "params": {
            "checkin": "2026-06-01",
            "checkout": "2026-06-03",
            "adults": 2,
            "rooms": 1,
            "children": 0,
        }
    }
    url = _search_url("Kathmandu hotel", ctx)
    assert "ss=Kathmandu+hotel" in url, url
    assert "checkin=2026-06-01" in url, url
    assert "checkout=2026-06-03" in url, url
    assert "group_adults=2" in url, url
    assert "no_rooms=1" in url, url


def test_direct_url_gets_booking_params() -> None:
    ctx = {"params": {"checkin": "2026-06-01", "checkout": "2026-06-02", "guests": 3}}
    url = _with_booking_params("https://www.booking.com/hotel/np/example.html?aid=1", ctx)
    assert "aid=1" in url, url
    assert "checkin=2026-06-01" in url, url
    assert "checkout=2026-06-02" in url, url
    assert "group_adults=3" in url, url


async def _run_confirmation_detection() -> None:
    page = _FakePage(
        "https://secure.booking.com/confirmation.html?booking_number=ABC12345",
        text=(
            "Your booking is confirmed\n"
            "Confirmation number ABC12345\n"
            "Thank you for booking with Booking.com\n"
            "Total Rs. 4500"
        ),
    )
    stage = await classify_checkout_page(page)
    assert stage == "success", stage

    adapter = BookingAdapter()
    assert await adapter.is_confirmation_page(page) is True
    receipt = await adapter.extract_receipt(page)
    assert receipt["source"] == "booking"
    assert receipt["order_id"] == "ABC12345"
    assert receipt["total"] == 4500.0


def main() -> int:
    failures: list[str] = []

    for name, func in (
        ("test_booking_search_url", test_booking_search_url),
        ("test_direct_url_gets_booking_params", test_direct_url_gets_booking_params),
    ):
        print(f"{name} ...", end=" ")
        try:
            func()
            print("OK")
        except Exception as e:
            print(f"FAIL: {e}")
            failures.append(f"{name}: {e}")

    print("test_confirmation_detection ...", end=" ")
    try:
        asyncio.run(_run_confirmation_detection())
        print("OK")
    except Exception as e:
        print(f"FAIL: {e}")
        failures.append(f"test_confirmation_detection: {e}")

    if failures:
        print(f"\n[FAIL] {len(failures)} test(s) failed.")
        return 1
    print("\n[PASS] All booking unit tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
