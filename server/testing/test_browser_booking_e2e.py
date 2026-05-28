"""End-to-end Booking.com handoff test.

This drives the browser agent to a safe Booking.com handoff point:
search/property page -> availability/details. It never clicks the final
"complete booking" action. If --watch is supplied, it waits for a real
Booking.com confirmation page after you finish the booking manually and
saves/emails the confirmation through the shared receipt watcher.

Usage:
  python server/testing/test_browser_booking_e2e.py \
      --url "https://www.booking.com/hotel/np/example.html" \
      --checkin 2026-06-01 --checkout 2026-06-02 --adults 2

  python server/testing/test_browser_booking_e2e.py \
      --query "Kathmandu hotel" \
      --checkin 2026-06-01 --checkout 2026-06-02 --watch
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from plugins.installed.web.browser.adapters.booking import BookingAdapter
from plugins.installed.web.browser.commerce.watcher import start_receipt_watch
from plugins.installed.web.browser.events import BrowserEventType, get_event_bus
from plugins.installed.web.browser.session import shutdown_browser_session

from testing.test_browser_youtube_e2e import EventRecorder, ensure_chrome_debug


def _params(args: argparse.Namespace) -> dict[str, Any]:
    out: dict[str, Any] = {
        "adults": args.adults,
        "rooms": args.rooms,
        "children": args.children,
    }
    if args.checkin:
        out["checkin"] = args.checkin
    if args.checkout:
        out["checkout"] = args.checkout
    return out


def _subscribe_terminal_events() -> None:
    bus = get_event_bus()

    def _cb(event):
        data = event.data or {}
        if event.type == BrowserEventType.CHECKOUT_STAGE_CHANGED:
            stage = data.get("stage") or "unknown"
            guidance = data.get("guidance") or ""
            print(f"\n  >> NOW AT [{stage.upper()}] {guidance}")
            print(f"     url: {data.get('url')}")
        elif event.type == BrowserEventType.AWAITING_USER:
            remaining = data.get("remaining_s")
            stage = data.get("stage") or "?"
            msg = data.get("message", "")
            rem = f" ({int(remaining)}s left)" if remaining is not None else ""
            print(f"  [watch{rem}] [{stage}] {msg}")
        elif event.type == BrowserEventType.RECEIPT_WATCH_STARTED:
            print(f"  [watch started] timeout={data.get('timeout_s')}s")
        elif event.type == BrowserEventType.RECEIPT_CAPTURED:
            print(f"\n  [captured] booking={data.get('order_id')} total={data.get('total')} {data.get('currency','')}")
        elif event.type == BrowserEventType.RECEIPT_EMAILED:
            if data.get("sent"):
                print(f"  [emailed] -> {data.get('to')} (id={data.get('id')})")
            else:
                print(f"  [email FAILED] {data.get('error')}")
        elif event.type == BrowserEventType.RECEIPT_WATCH_TIMEOUT:
            print(f"  [watch timeout] after {data.get('duration_s'):.0f}s")

    for et in (
        BrowserEventType.AWAITING_USER,
        BrowserEventType.RECEIPT_WATCH_STARTED,
        BrowserEventType.CHECKOUT_STAGE_CHANGED,
        BrowserEventType.RECEIPT_CAPTURED,
        BrowserEventType.RECEIPT_EMAILED,
        BrowserEventType.RECEIPT_WATCH_TIMEOUT,
    ):
        bus.subscribe(et, _cb)


async def run(args: argparse.Namespace) -> int:
    ensure_chrome_debug()
    target = args.url or args.query
    if not target:
        print("[FAIL] Provide --url or --query.")
        return 2

    from plugins.installed.web.browser.tool import BrowserAgentTool

    recorder = EventRecorder()
    print("=" * 60)
    print(f"Booking.com e2e -- target={target!r}")
    print("=" * 60)
    print("The agent will stop before any final booking/payment submit.")

    result = await BrowserAgentTool()._execute({
        "intent": "book_hotel",
        "query": target,
        "params": _params(args),
        "dry_run": False,
        "approve_payment": True,
    })

    print(f"\nflow.success = {result.success}")
    print(f"flow.state   = {(result.data or {}).get('state')}")
    if result.error:
        print(f"flow.error   = {result.error}")
    context = (result.data or {}).get("context") or {}
    if context.get("url"):
        print(f"handoff.url  = {context['url']}")
    if context.get("booking_stage"):
        print(f"handoff.stage= {context['booking_stage']}")

    if (result.data or {}).get("state") != "payment_handoff":
        await shutdown_browser_session()
        return 1

    print("\n[handoff] Continue in Chrome. Spark will not click the final booking button.")
    if not args.watch:
        print("[done] Re-run with --watch if you want Spark to wait for confirmation capture.")
        await shutdown_browser_session()
        return 0

    _subscribe_terminal_events()
    task = start_receipt_watch(
        BookingAdapter(),
        timeout_s=args.watch_timeout,
        poll_every_s=2.0,
        reminder_every_s=30.0,
        desktop_reminder_every_s=10.0,
        desktop_reminder_max_s=120.0,
    )
    watch_result = await task

    print("=" * 60)
    if watch_result.captured:
        print("[CAPTURED]")
        saved = watch_result.saved
        if saved:
            print(f"  dir          = {saved.dir}")
            print(f"  receipt      = {saved.receipt_path.name}")
            print(f"  screenshot   = {saved.screenshot_path.name if saved.screenshot_path else '<missing>'}")
            print(f"  html         = {saved.html_path.name if saved.html_path else '<missing>'}")
            print(f"  booking.id   = {saved.data.get('order_id')}")
            print(f"  total        = {saved.data.get('total')} {saved.data.get('currency') or ''}")
        print(f"  email.sent   = {watch_result.email.get('sent')}")
    elif watch_result.timed_out:
        print(f"[TIMEOUT] watcher gave up after {watch_result.duration_s:.0f}s.")
    else:
        print(f"[ERROR] watcher crashed: {watch_result.error}")
    print("=" * 60)
    print(f"\nEvents fired: {[e.type.value for e in recorder.events]}")

    await shutdown_browser_session()
    return 0 if watch_result.captured else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="Booking.com hotel URL.")
    parser.add_argument("--query", help="Booking.com search query.")
    parser.add_argument("--checkin", help="YYYY-MM-DD check-in date.")
    parser.add_argument("--checkout", help="YYYY-MM-DD check-out date.")
    parser.add_argument("--adults", type=int, default=1)
    parser.add_argument("--rooms", type=int, default=1)
    parser.add_argument("--children", type=int, default=0)
    parser.add_argument("--watch", action="store_true", help="Wait for confirmation capture after handoff.")
    parser.add_argument("--watch-timeout", type=float, default=900.0)
    args = parser.parse_args()

    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        try:
            asyncio.run(shutdown_browser_session())
        except Exception:
            pass
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
