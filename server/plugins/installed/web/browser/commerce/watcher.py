"""Post-payment receipt watcher.

What it does
────────────
Once a purchase flow hits ``PAYMENT_HANDOFF``, the agent steps aside
so the user can finish the actual payment (UPI, eSewa, card, COD, ...).
This watcher is the agent's *eyes* during that step: it polls the live
tab in the background, and the moment the site renders the order
confirmation page it captures the receipt, saves to disk, and emails
the user.

Why a separate background task
──────────────────────────────
The state machine treats PAYMENT_HANDOFF as terminal — and rightly so;
we never want the flow to programmatically click "Place Order". But
"terminal for the flow" is not "terminal for the agent". The watcher
runs OUT-OF-BAND of any flow, holding a reference to the shared
``BrowserSession`` page, polling on a slow cadence (~2s) so we don't
hammer the SPA. It returns control to the user immediately.

Adapter contract
────────────────
The watcher knows nothing about Daraz/Amazon/Booking. It calls into
the adapter via duck typing:

  * ``adapter.is_confirmation_page(page) -> bool``  (async)
      Returns True when the live tab shows an order-success page.

  * ``adapter.extract_receipt(page) -> dict``  (async)
      Returns the receipt dict to persist + email. Should include
      whatever the adapter could reliably scrape; commerce.receipt
      handles the envelope.

Any adapter that defines those two methods gets the watcher for free.

Lifecycle
─────────
``start_receipt_watch`` fires the coroutine as a fire-and-forget
``asyncio.Task`` and returns it. The caller doesn't need to await it —
the result lands in the event bus (RECEIPT_CAPTURED / RECEIPT_EMAILED /
RECEIPT_WATCH_TIMEOUT) and on disk. For tests, ``await``ing the task
gives you the full ``ReceiptWatchResult``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from ..events import BrowserEvent, BrowserEventType, get_event_bus
from ..notify import clear_notifications, notify, notify_stage_change
from ..session import get_browser_session
from .receipt import capture_page_artifacts, save_receipt, SavedReceipt
from .email import send_receipt_email, DEFAULT_RECIPIENT

logger = logging.getLogger(__name__)


# ── Adapter protocol ───────────────────────────────────────────────────────

class _CommerceAdapter(Protocol):
    """Duck-typed contract a commerce adapter must satisfy."""
    name: str
    base_url: str

    async def is_confirmation_page(self, page: Any) -> bool: ...
    async def extract_receipt(self, page: Any) -> dict: ...


# ── Result ─────────────────────────────────────────────────────────────────

@dataclass
class ReceiptWatchResult:
    """What the watcher emits at the end of its life."""
    captured: bool
    timed_out: bool
    saved: Optional[SavedReceipt] = None
    email: dict = field(default_factory=dict)  # whatever send_receipt_email returned
    error: Optional[str] = None
    duration_s: float = 0.0


# ── Public API ─────────────────────────────────────────────────────────────

def start_receipt_watch(
    adapter: _CommerceAdapter,
    *,
    host_match: Optional[str] = None,
    to_email: Optional[str] = None,
    user_name: str = "there",
    timeout_s: float = 300.0,
    poll_every_s: float = 2.0,
    reminder_every_s: float = 30.0,
    desktop_reminder_every_s: float = 10.0,
    desktop_reminder_max_s: float = 120.0,
) -> asyncio.Task[ReceiptWatchResult]:
    """Fire the watcher as a background task. Returns the Task.

    The caller (tools/browser_action.py) wants to return to the user
    immediately while the watcher keeps running — so this never blocks.
    The task settles on the event loop and surfaces its lifecycle via
    the event bus + disk.
    """
    coro = _watch_for_receipt(
        adapter,
        host_match=host_match or _host_from(adapter.base_url),
        to_email=to_email,
        user_name=user_name,
        timeout_s=timeout_s,
        poll_every_s=poll_every_s,
        reminder_every_s=reminder_every_s,
        desktop_reminder_every_s=desktop_reminder_every_s,
        desktop_reminder_max_s=desktop_reminder_max_s,
    )
    return asyncio.create_task(coro, name=f"receipt-watch-{adapter.name}")


# ── Implementation ─────────────────────────────────────────────────────────

async def _watch_for_receipt(
    adapter: _CommerceAdapter,
    *,
    host_match: str,
    to_email: Optional[str],
    user_name: str,
    timeout_s: float,
    poll_every_s: float,
    reminder_every_s: float,
    desktop_reminder_every_s: float,
    desktop_reminder_max_s: float,
) -> ReceiptWatchResult:
    bus = get_event_bus()
    started_at = asyncio.get_event_loop().time()

    bus.emit(BrowserEvent(
        type=BrowserEventType.RECEIPT_WATCH_STARTED,
        data={
            "source": adapter.name,
            "host": host_match,
            "timeout_s": timeout_s,
            "to": to_email or DEFAULT_RECIPIENT,
        },
    ))
    # Initial OS toast: the user is in Chrome at this point, not looking
    # at the terminal. They need a real popup to know the agent has
    # handed off and what to do next.
    notify(
        f"{adapter.name.capitalize()} — your turn",
        "Complete the checkout in Chrome. I'll save & email the receipt automatically.",
        sound=True,
    )

    session = get_browser_session()
    last_reminder = started_at
    last_desktop_reminder = started_at
    last_stage: Optional[str] = None
    last_url: Optional[str] = None

    # Adapters may provide ``classify_checkout_stage(url)`` and
    # ``STAGE_GUIDANCE`` for accurate multi-step progress messages.
    # Watcher works without them — generic guidance is the fallback.
    classify = getattr(_adapter_module(adapter), "classify_checkout_stage", None)
    classify_page = getattr(_adapter_module(adapter), "classify_checkout_page", None)
    stage_guidance: dict = getattr(_adapter_module(adapter), "STAGE_GUIDANCE", {}) or {}

    try:
        while True:
            now = asyncio.get_event_loop().time()
            elapsed = now - started_at
            if elapsed >= timeout_s:
                duration = now - started_at
                logger.warning(
                    "receipt watcher (%s): timed out after %.0fs", adapter.name, duration
                )
                bus.emit(BrowserEvent(
                    type=BrowserEventType.RECEIPT_WATCH_TIMEOUT,
                    data={"source": adapter.name, "duration_s": duration},
                ))
                clear_notifications()
                notify(
                    f"{adapter.name.capitalize()} — watcher gave up",
                    f"No order confirmation seen after {int(duration)}s. "
                    "If you completed the payment, check your orders.",
                    sound=True,
                )
                return ReceiptWatchResult(
                    captured=False, timed_out=True, duration_s=duration,
                    error="watch timeout",
                )

            # Grab the live page (no refocus — user is in another window
            # paying; pulling focus would be hostile).
            try:
                page = await session.get_page(host_match, focus=False)
            except Exception as e:
                logger.debug("receipt watcher: get_page failed (retry): %s", e)
                await asyncio.sleep(poll_every_s)
                continue

            # Detect checkout-stage transitions. Prefer a DOM-aware adapter
            # classifier when present: Daraz can remain on /shipping even
            # after the saved address is ready and the visible CTA changes
            # to "Proceed to Pay".
            current_url = (getattr(page, "url", None) or "")
            if current_url != last_url:
                last_url = current_url
            try:
                if classify_page:
                    current_stage = await classify_page(page)
                else:
                    current_stage = classify(current_url) if classify else "unknown"
            except Exception as e:
                logger.debug("receipt watcher: classify stage failed (retry): %s", e)
                current_stage = classify(current_url) if classify else "unknown"
            current_stage = str(current_stage or "unknown")

            if current_stage != last_stage:
                last_stage = current_stage
                guidance = stage_guidance.get(current_stage)
                bus.emit(BrowserEvent(
                    type=BrowserEventType.CHECKOUT_STAGE_CHANGED,
                    data={
                        "source": adapter.name,
                        "stage": current_stage,
                        "url": current_url,
                        "guidance": guidance,
                    },
                ))
                if guidance:
                    bus.emit(BrowserEvent(
                        type=BrowserEventType.AWAITING_USER,
                        data={
                            "reason": "awaiting_checkout",
                            "source": adapter.name,
                            "stage": current_stage,
                            "remaining_s": max(0.0, timeout_s - elapsed),
                            "message": guidance,
                            "reminder": False,
                        },
                    ))
                # OS toast — this is the headline UX. The user is in
                # Chrome, not the terminal; the toast tells them what
                # they have to do next.
                notify_stage_change(adapter.name, current_stage, guidance)
                # Reset reminder clock so we don't double-print right after a stage change.
                last_reminder = now

            # Periodic AWAITING_USER reminder. Use the adapter's
            # stage-specific guidance when we know the stage; otherwise a
            # generic message. Way more useful than the previous "still
            # waiting for payment" that fired even on the address page.
            if reminder_every_s > 0 and (now - last_reminder) >= reminder_every_s:
                last_reminder = now
                guidance = stage_guidance.get(last_stage or "unknown") if stage_guidance else None
                msg = guidance or (
                    f"Working through your {adapter.name} purchase. "
                    "I'll save and email the receipt once the order is placed."
                )
                bus.emit(BrowserEvent(
                    type=BrowserEventType.AWAITING_USER,
                    data={
                        "reason": "awaiting_checkout",
                        "source": adapter.name,
                        "stage": last_stage,
                        "remaining_s": max(0.0, timeout_s - elapsed),
                        "message": msg,
                        "reminder": True,
                    },
                ))

            # Bounded desktop reminders: useful while the user is actively
            # in checkout, but never allowed to become an endless OS-popup
            # loop. Stage changes, success, and timeout still notify outside
            # this window.
            if (
                desktop_reminder_every_s > 0
                and desktop_reminder_max_s > 0
                and elapsed <= desktop_reminder_max_s
                and (now - last_desktop_reminder) >= desktop_reminder_every_s
            ):
                last_desktop_reminder = now
                guidance = stage_guidance.get(last_stage or "unknown") if stage_guidance else None
                msg = guidance or (
                    f"Working through your {adapter.name} purchase. "
                    "I'll save and email the receipt once the order is placed."
                )
                notify(
                    f"{adapter.name.capitalize()} — still waiting",
                    msg,
                    sound=False,
                    tag=f"{adapter.name}-checkout-reminder",
                    group="checkout-reminders",
                    allow_popup_fallback=False,
                )

            # Adapter-specific confirmation detection.
            try:
                done = await adapter.is_confirmation_page(page)
            except Exception as e:
                logger.debug("receipt watcher: is_confirmation_page error (retry): %s", e)
                done = False

            if done:
                return await _capture_and_deliver(
                    adapter, page, started_at,
                    to_email=to_email, user_name=user_name, bus=bus,
                )

            await asyncio.sleep(poll_every_s)

    except asyncio.CancelledError:
        # Shutdown — propagate cancellation so the event loop tears down cleanly.
        logger.info("receipt watcher (%s): cancelled", adapter.name)
        raise
    except Exception as e:
        logger.exception("receipt watcher (%s): crashed", adapter.name)
        duration = asyncio.get_event_loop().time() - started_at
        bus.emit(BrowserEvent(
            type=BrowserEventType.RECEIPT_WATCH_TIMEOUT,
            data={"source": adapter.name, "duration_s": duration, "crashed": True, "error": str(e)},
        ))
        return ReceiptWatchResult(
            captured=False, timed_out=False, duration_s=duration, error=str(e)
        )


async def _capture_and_deliver(
    adapter: _CommerceAdapter,
    page: Any,
    started_at: float,
    *,
    to_email: Optional[str],
    user_name: str,
    bus: Any,
) -> ReceiptWatchResult:
    """Confirmation page detected — scrape, persist, email."""
    duration = asyncio.get_event_loop().time() - started_at

    # 1. Adapter scrapes the page for whatever it can find.
    try:
        receipt = await adapter.extract_receipt(page)
    except Exception as e:
        logger.exception("receipt watcher (%s): extract_receipt failed", adapter.name)
        receipt = {"source": adapter.name, "source_url": page.url, "error": str(e)}

    receipt.setdefault("source", adapter.name)
    receipt.setdefault("source_url", page.url)
    receipt.setdefault("captured_at", time.time())

    # 2. Persist envelope, then snapshot the page into the same dir.
    saved = save_receipt(receipt)
    artifacts = await capture_page_artifacts(page, saved.dir)
    if artifacts.get("screenshot"):
        saved.screenshot_path = artifacts["screenshot"]
    if artifacts.get("html"):
        saved.html_path = artifacts["html"]

    bus.emit(BrowserEvent(
        type=BrowserEventType.RECEIPT_CAPTURED,
        data={
            "source": adapter.name,
            "order_id": receipt.get("order_id"),
            "total": receipt.get("total"),
            "currency": receipt.get("currency"),
            "dir": str(saved.dir),
            "duration_s": duration,
        },
    ))

    # 3. Email (best-effort). Failure here doesn't undo step 2.
    email_result = send_receipt_email(receipt, to_email=to_email, user_name=user_name)
    bus.emit(BrowserEvent(
        type=BrowserEventType.RECEIPT_EMAILED,
        data={
            "source": adapter.name,
            "sent": email_result.get("sent", False),
            "to": email_result.get("to"),
            "id": email_result.get("id"),
            "error": email_result.get("error"),
        },
    ))
    clear_notifications()
    if email_result.get("sent"):
        notify(
            f"{adapter.name.capitalize()} — receipt captured",
            f"Saved the receipt and emailed it to {email_result.get('to')}.",
            sound=True,
        )
    else:
        notify(
            f"{adapter.name.capitalize()} — receipt saved",
            f"Receipt saved in {saved.dir}. Email failed: {email_result.get('error') or 'unknown error'}",
            sound=True,
        )

    # 4. Write the email-delivery outcome back into the saved receipt so
    # the on-disk record is self-contained.
    receipt["delivery"] = email_result
    saved.receipt_path.write_text(
        json.dumps(receipt, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )

    return ReceiptWatchResult(
        captured=True, timed_out=False, saved=saved,
        email=email_result, duration_s=duration,
    )


# ── Helpers ────────────────────────────────────────────────────────────────

def _host_from(base_url: str) -> str:
    from urllib.parse import urlparse
    h = urlparse(base_url).netloc.lower()
    return h.removeprefix("www.") or base_url


def _adapter_module(adapter: Any):
    """Return the module that defines ``adapter`` so the watcher can look
    up adapter-supplied helpers like ``classify_checkout_stage`` and
    ``STAGE_GUIDANCE``. Returns the adapter itself as a fallback so a
    missing attribute just degrades to "unknown" rather than crashing.
    """
    import sys
    mod_name = type(adapter).__module__
    return sys.modules.get(mod_name, adapter)


__all__ = ["start_receipt_watch", "ReceiptWatchResult"]
