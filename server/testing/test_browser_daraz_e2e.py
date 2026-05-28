"""End-to-end Daraz Buy Now test — two-stage, real money on Stage 2.

Why two stages
──────────────
Pressing "Buy Now" in production charges real currency. To avoid
surprise purchases we ALWAYS:
  1. Stage 1 (default): open Chrome, navigate to the product page,
     auto-pick the first variant, print product title + price.
     Stop there. No Buy Now click. No agent flow past SELECT.
  2. Stage 2 (opt-in via --buy): only after you typed `yes` at the
     prompt — drive the full flow until PAYMENT_HANDOFF, then spawn
     the watcher. The agent NEVER submits the payment form regardless
     of any flag (state machine enforces this).

Two ways to specify the product
───────────────────────────────
  --product-url   Daraz product page URL.  SAFEST. You see exactly
                  what you're buying.
  --query         Free-text search; the agent picks the first result.
                  Use only if you trust the search ordering.

Usage
─────
  # Inspect only (no purchase risk):
  python server/testing/test_browser_daraz_e2e.py \\
      --product-url "https://www.daraz.com.np/products/<your-product>.html"

  # Buy after manual confirmation:
  python server/testing/test_browser_daraz_e2e.py \\
      --product-url "https://www.daraz.com.np/products/<your-product>.html" \\
      --buy

First run: sign in to Daraz when Chrome opens — persistent profile
keeps the session forever after.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from plugins.installed.web.browser.session import (
    get_browser_session,
    shutdown_browser_session,
)
from plugins.installed.web.browser.adapters.daraz import (
    DarazAdapter,
    DARAZ_AUTH,
    _auto_pick_variants,
    _search_url,
    _looks_like_url,
)
from plugins.installed.web.browser.auth import ensure_signed_in
from plugins.installed.web.browser.events import BrowserEventType, get_event_bus

# Reuse Chrome bring-up + event recorder from the YouTube e2e module.
from testing.test_browser_youtube_e2e import ensure_chrome_debug, EventRecorder


# ─── Stage 1: navigate to product page, summarize ──────────────────────────

async def _inspect_product(target: str) -> dict[str, Any]:
    """Open the product page (URL or search-first-result), auto-pick
    variants, scrape title + price. Does NOT click Buy Now."""
    session = get_browser_session()
    page = await session.get_page("daraz.com.np", focus=True)

    # Make sure we're signed in first — Buy Now is gated on login, and we
    # want the test to fail fast at auth rather than at checkout.
    runtime = await session.runtime()
    signed = await ensure_signed_in(page, DARAZ_AUTH, runtime, timeout_s=120.0)
    if not signed:
        return {"ok": False, "stage": "auth", "reason": "Daraz sign-in not completed"}

    # Navigate.
    if _looks_like_url(target):
        await page.goto(target, wait_until="domcontentloaded", timeout=20_000)
    else:
        await page.goto(_search_url(target), wait_until="domcontentloaded", timeout=20_000)
        # Click first product card.
        from plugins.installed.web.browser.adapters.daraz import click_first_product
        from plugins.installed.web.browser.action_graph import StepContext
        step = click_first_product()
        await step.run(StepContext(page, target, {}, runtime))

    # Settle + auto-pick variants so the price reflects them.
    await page.wait_for_timeout(1500)
    variants = await _auto_pick_variants(page)
    await page.wait_for_timeout(500)

    title = (await page.title()).strip()
    price = await page.evaluate("""
        () => {
            const candidates = [
                '.pdp-price_type_normal',
                '.pdp-price_color_orange',
                '.pdp-product-price',
                '[class*="pdp-price"]',
                '.notranslate',
            ];
            for (const sel of candidates) {
                const el = document.querySelector(sel);
                if (el && el.innerText.trim()) return el.innerText.trim();
            }
            return null;
        }
    """)

    return {
        "ok": True,
        "stage": "inspected",
        "url": page.url,
        "title": title,
        "price": price,
        "variants_picked": variants,
    }


def _confirm_purchase(info: dict[str, Any]) -> bool:
    """Print the summary and require a literal 'yes' from stdin."""
    print()
    print("=" * 60)
    print("ABOUT TO PRESS BUY NOW")
    print("=" * 60)
    print(f"  URL:       {info.get('url')}")
    print(f"  Title:     {info.get('title')}")
    print(f"  Price:     {info.get('price') or '<not detected>'}")
    if info.get("variants_picked"):
        print(f"  Variants:  {info['variants_picked']}")
    print()
    print("The agent will press Buy Now and let YOU complete payment in Chrome.")
    print("Nothing is submitted on your behalf. Receipt will be saved + emailed.")
    print()
    answer = input("Type 'yes' to proceed, anything else to abort: ").strip().lower()
    return answer == "yes"


# ─── Stage 2: run the full flow + watch for receipt ────────────────────────

async def _buy(target: str, watch_timeout_s: float) -> dict[str, Any]:
    """Drive the BrowserAgentTool for ``buy_product``; spawn the watcher;
    keep this script alive until the watcher resolves so we can print
    its outcome. In production the watcher is fire-and-forget."""
    from plugins.installed.web.browser.tool import BrowserAgentTool
    from plugins.installed.web.browser.commerce.watcher import start_receipt_watch

    recorder = EventRecorder()

    print("\n[stage 2] Running buy_product flow ...")
    result = await BrowserAgentTool()._execute({
        "intent": "buy_product",
        "query": target,
        "dry_run": False,
        "approve_payment": True,  # see browser_action.py comment for semantics
    })

    print(f"  flow.success = {result.success}")
    print(f"  flow.state   = {(result.data or {}).get('state')}")
    if result.error:
        print(f"  flow.error   = {result.error}")

    state = (result.data or {}).get("state")
    if state != "payment_handoff":
        return {"ok": False, "stage": "flow", "result": result.data, "error": result.error}

    print(f"\n[stage 2] Buy Now clicked. Daraz has a 4-step checkout — handing off to you.")
    print(f"           Watcher armed for {watch_timeout_s:.0f}s.")
    print()
    print("           Daraz checkout stages (watcher will announce each):")
    print("             1. SHIPPING  — pick or confirm address, then Proceed to Pay")
    print("             2. CONFIRM   — review order, pick payment method, Place Order")
    print("             3. GATEWAY   — eSewa / Khalti / card (they re-ask for login)")
    print("             4. SUCCESS   — receipt is captured + emailed automatically")
    print()

    # Stream the watcher's events to the terminal so the user knows
    # the agent is still alive and what it's doing. Silent watching for
    # 5 minutes makes the assistant feel dead.
    bus = get_event_bus()

    def _print_event(prefix: str):
        def _cb(event):
            data = event.data or {}
            if event.type == BrowserEventType.CHECKOUT_STAGE_CHANGED:
                stage = data.get("stage") or "unknown"
                guidance = data.get("guidance") or ""
                print(f"\n  >> NOW AT [{stage.upper()}] {guidance}")
                print(f"     url: {data.get('url')}")
            elif event.type == BrowserEventType.AWAITING_USER:
                remaining = data.get("remaining_s")
                msg = data.get("message", "")
                stage = data.get("stage") or "?"
                remaining_str = f" ({int(remaining)}s left)" if remaining is not None else ""
                print(f"  [watch{remaining_str}] [{stage}] {msg}")
            elif event.type == BrowserEventType.RECEIPT_WATCH_STARTED:
                print(f"  [watch started] timeout={data.get('timeout_s')}s")
            elif event.type == BrowserEventType.RECEIPT_CAPTURED:
                print(f"\n  [captured] order={data.get('order_id')} total={data.get('total')} {data.get('currency','')}")
            elif event.type == BrowserEventType.RECEIPT_EMAILED:
                if data.get("sent"):
                    print(f"  [emailed] -> {data.get('to')} (id={data.get('id')})")
                else:
                    print(f"  [email FAILED] {data.get('error')}")
            elif event.type == BrowserEventType.RECEIPT_WATCH_TIMEOUT:
                print(f"  [watch timeout] after {data.get('duration_s'):.0f}s")
        return _cb

    for et in (BrowserEventType.AWAITING_USER,
               BrowserEventType.RECEIPT_WATCH_STARTED,
               BrowserEventType.CHECKOUT_STAGE_CHANGED,
               BrowserEventType.RECEIPT_CAPTURED,
               BrowserEventType.RECEIPT_EMAILED,
               BrowserEventType.RECEIPT_WATCH_TIMEOUT):
        bus.subscribe(et, _print_event(et.value))

    watch_task = start_receipt_watch(
        DarazAdapter(),
        timeout_s=watch_timeout_s,
        poll_every_s=2.0,
        reminder_every_s=20.0,  # tighter than default — user wants visibility
    )
    watch_result = await watch_task

    print("=" * 60)
    if watch_result.captured:
        print("[CAPTURED]")
        s = watch_result.saved
        if s:
            print(f"  dir         = {s.dir}")
            print(f"  receipt     = {s.receipt_path.name}")
            print(f"  screenshot  = {s.screenshot_path.name if s.screenshot_path else '<missing>'}")
            print(f"  html        = {s.html_path.name if s.html_path else '<missing>'}")
            print(f"  data.order  = {s.data.get('order_id')}")
            print(f"  data.total  = {s.data.get('total')} {s.data.get('currency') or ''}")
        print(f"  email.sent  = {watch_result.email.get('sent')}")
        if not watch_result.email.get("sent"):
            print(f"  email.error = {watch_result.email.get('error')}")
    elif watch_result.timed_out:
        print(f"[TIMEOUT] watcher gave up after {watch_result.duration_s:.0f}s.")
        print("          Payment may still go through; check your Daraz orders.")
    else:
        print(f"[ERROR] watcher crashed: {watch_result.error}")
    print("=" * 60)

    print(f"\nEvents fired: {[e.type.value for e in recorder.events]}")
    return {"ok": watch_result.captured, "result": result.data, "watch": watch_result}


# ─── Entry point ───────────────────────────────────────────────────────────

async def run(args: argparse.Namespace) -> int:
    ensure_chrome_debug()

    target = args.product_url or args.query
    if not target:
        print("[FAIL] Provide --product-url or --query.")
        return 2

    print("=" * 60)
    print(f"Daraz e2e -- target={target!r}  buy={args.buy}")
    print("=" * 60)
    if not args.product_url:
        print("[warn] No --product-url given — using --query and clicking the first")
        print("       search result. For a real-money test prefer --product-url.")

    # Stage 1 — always.
    info = await _inspect_product(target)
    if not info.get("ok"):
        print(f"[FAIL] inspection: {info}")
        return 1

    print()
    print("PRODUCT")
    print(f"  url     {info['url']}")
    print(f"  title   {info['title']}")
    print(f"  price   {info['price'] or '<not detected>'}")
    if info["variants_picked"]:
        print(f"  variant {info['variants_picked']}")

    if not args.buy:
        print("\n[stage 1 only] Inspect complete. Re-run with --buy to actually purchase.")
        await shutdown_browser_session()
        return 0

    # Stage 2 — explicit confirmation gate.
    if not _confirm_purchase(info):
        print("Aborted at confirmation gate. No purchase made.")
        await shutdown_browser_session()
        return 0

    result = await _buy(target, watch_timeout_s=args.watch_timeout)
    await shutdown_browser_session()
    return 0 if result.get("ok") else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--product-url",
        help="Daraz product page URL (recommended — exact item).",
    )
    parser.add_argument(
        "--query",
        help="Free-text search; agent picks first result. Riskier.",
    )
    parser.add_argument(
        "--buy", action="store_true",
        help="Actually press Buy Now and watch for receipt. Default: inspect only.",
    )
    parser.add_argument(
        "--watch-timeout", type=float, default=300.0,
        help="How long the receipt watcher waits for /order/success/ (seconds). Default 300s.",
    )
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
    sys.exit(main())
