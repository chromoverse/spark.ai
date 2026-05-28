"""Booking.com hotel adapter - hotel page -> availability -> user handoff.

Safety contract
---------------
The adapter may open a hotel/search page and click low-risk navigation such
as "See availability". It does not click the final "Complete booking" /
"Book now" submit action. Once the user is at room selection or booking
details, the flow enters PAYMENT_HANDOFF and the shared watcher waits for a
confirmation page if the user completes the booking manually.
"""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import parse_qsl, quote_plus, urlencode, urlparse, urlunparse

from .base import SiteAdapter, SiteCapabilities
from ..action_graph import ActionGraph, ActionStep, StepContext
from ..errors import BrowserError, BrowserErrorType
from ..semantic import ActionResult, goto, wait_navigation
from ..state_machine import FlowState

logger = logging.getLogger(__name__)


BOOKING_HOST_HINTS = ("booking.com", "www.booking.com")

CONFIRMATION_URL_FRAGMENTS = (
    "/confirmation",
    "booking-confirmation",
    "confirmation.html",
)

CONFIRMATION_TEXT_MARKERS = (
    "your booking is confirmed",
    "booking confirmed",
    "confirmation number",
    "booking number",
    "reservation number",
    "thank you for booking",
)

DETAILS_TEXT_MARKERS = (
    "enter your details",
    "your details",
    "guest details",
    "payment details",
    "complete booking",
)

PAYMENT_TEXT_MARKERS = (
    "payment method",
    "card number",
    "cvc",
    "cvv",
    "pay now",
)

AVAILABILITY_TEXT_MARKERS = (
    "select rooms",
    "choose your room",
    "availability",
    "reserve",
    "bed type",
)


STAGE_GUIDANCE = {
    "search": "Choose the hotel you want from the Booking.com results.",
    "property": "Review the property, dates, room rules, and click See availability if needed.",
    "availability": "Choose a room/rate and click Reserve. Spark will not complete the booking for you.",
    "details": "Fill guest/payment details and review carefully. Only you click the final booking button.",
    "payment": "Complete payment or booking if you want. Spark will capture the confirmation afterward.",
    "success": "Booking confirmed. Capturing confirmation...",
    "unknown": "Working through the Booking.com flow...",
}


def _looks_like_url(value: str) -> bool:
    value = (value or "").strip().lower()
    return value.startswith(("http://", "https://")) or "booking.com" in value


def _is_booking_url(value: str) -> bool:
    host = urlparse(value if "://" in value else f"https://{value}").netloc.lower()
    return any(h in host for h in BOOKING_HOST_HINTS)


def _first_str(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _positive_int(value: Any, default: int, *, minimum: int = 0) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, n)


def _booking_params(ctx: dict) -> dict[str, str]:
    params = ctx.get("params") if isinstance(ctx.get("params"), dict) else ctx
    checkin = _first_str(
        params.get("checkin"),
        params.get("check_in"),
        params.get("checkin_date"),
        params.get("date_from"),
    )
    checkout = _first_str(
        params.get("checkout"),
        params.get("check_out"),
        params.get("checkout_date"),
        params.get("date_to"),
    )
    adults = _positive_int(params.get("adults", params.get("guests")), 1, minimum=1)
    rooms = _positive_int(params.get("rooms"), 1, minimum=1)
    children = _positive_int(params.get("children"), 0, minimum=0)

    out = {
        "group_adults": str(adults),
        "no_rooms": str(rooms),
        "group_children": str(children),
    }
    if checkin and checkout:
        out["checkin"] = checkin
        out["checkout"] = checkout
    return out


def _search_url(query: str, ctx: dict) -> str:
    query_params = {
        "ss": query,
        "sb": "1",
        "src": "searchresults",
        **_booking_params(ctx),
    }
    return f"https://www.booking.com/searchresults.html?{urlencode(query_params)}"


def _with_booking_params(url: str, ctx: dict) -> str:
    if not _is_booking_url(url):
        return url
    parsed = urlparse(url)
    existing = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in _booking_params(ctx).items():
        existing.setdefault(key, value)
    return urlunparse(parsed._replace(query=urlencode(existing)))


async def _page_text(page: Any) -> str:
    try:
        text = await page.evaluate(
            "() => document.body && document.body.innerText ? document.body.innerText : ''"
        )
        return str(text or "").lower()
    except Exception:
        return ""


async def _looks_like_confirmation_page(page: Any) -> bool:
    url = (getattr(page, "url", "") or "").lower()
    if any(fragment in url for fragment in CONFIRMATION_URL_FRAGMENTS):
        return True
    text = await _page_text(page)
    if not text:
        return False
    hits = sum(1 for marker in CONFIRMATION_TEXT_MARKERS if marker in text)
    return hits >= 2


def classify_checkout_stage(url: str) -> str:
    url = (url or "").lower()
    if any(fragment in url for fragment in CONFIRMATION_URL_FRAGMENTS):
        return "success"
    if "searchresults" in url:
        return "search"
    if "/hotel/" in url:
        return "property"
    if "book.html" in url or "checkout" in url:
        return "details"
    return "unknown"


async def classify_checkout_page(page: Any) -> str:
    if await _looks_like_confirmation_page(page):
        return "success"

    url_stage = classify_checkout_stage(getattr(page, "url", "") or "")
    text = await _page_text(page)
    if any(marker in text for marker in PAYMENT_TEXT_MARKERS):
        return "payment"
    if any(marker in text for marker in DETAILS_TEXT_MARKERS):
        return "details"
    if any(marker in text for marker in AVAILABILITY_TEXT_MARKERS):
        return "availability"
    return url_stage


async def _dismiss_popups(page: Any) -> None:
    selectors = (
        'button[aria-label="Dismiss sign-in info."]',
        'button[aria-label="Dismiss sign in information."]',
        'button[aria-label="Close"]',
        'button:has-text("Not now")',
        'button:has-text("No thanks")',
    )
    for selector in selectors:
        try:
            loc = page.locator(selector).first
            if await loc.count() and await loc.is_visible():
                await loc.click(timeout=1_500)
                await page.wait_for_timeout(300)
                return
        except Exception:
            continue


def _click_first_property() -> ActionStep:
    selectors = (
        'a[data-testid="title-link"]',
        '[data-testid="property-card"] a[href*="/hotel/"]',
        'a[href*="/hotel/"]:visible',
    )

    async def run(ctx: StepContext) -> ActionResult:
        await _dismiss_popups(ctx.page)
        for selector in selectors:
            try:
                loc = ctx.page.locator(selector).first
                await loc.wait_for(state="visible", timeout=8_000)
                href = await loc.get_attribute("href")
                if not href:
                    continue
                await ctx.page.goto(href, wait_until="domcontentloaded", timeout=20_000)
                await wait_navigation(ctx.page)
                return ActionResult(
                    ok=True,
                    action="click_first_booking_property",
                    target=href,
                    confidence=0.9,
                    evidence={"strategy": selector},
                )
            except Exception as e:
                logger.debug("booking: property selector %s missed: %s", selector, e)
        return ActionResult(
            ok=False,
            action="click_first_booking_property",
            target="first Booking.com property",
            confidence=0.0,
            error_type=BrowserErrorType.ELEMENT_NOT_FOUND,
            error_detail="No visible Booking.com property result was found",
        )

    return ActionStep(
        name="click_first_booking_property",
        goal="Open first Booking.com property result",
        run=run,
    )


def _click_see_availability() -> ActionStep:
    selectors = (
        'button[data-testid="availability-cta-btn"]',
        'a[data-testid="availability-cta-btn"]',
        'button:has-text("See availability")',
        'a:has-text("See availability")',
        'button:has-text("Select your room")',
        'a:has-text("Select your room")',
    )

    async def run(ctx: StepContext) -> ActionResult:
        await _dismiss_popups(ctx.page)
        for selector in selectors:
            try:
                loc = ctx.page.locator(selector).first
                if not await loc.count():
                    continue
                await loc.scroll_into_view_if_needed(timeout=3_000)
                await loc.click(timeout=5_000)
                await ctx.page.wait_for_timeout(1_500)
                return ActionResult(
                    ok=True,
                    action="click_see_availability",
                    target=selector,
                    confidence=0.85,
                )
            except Exception as e:
                logger.debug("booking: availability selector %s missed: %s", selector, e)

        stage = await classify_checkout_page(ctx.page)
        if stage in {"availability", "details", "payment", "success"}:
            return ActionResult(
                ok=True,
                action="click_see_availability",
                target=stage,
                confidence=0.75,
                evidence={"already_at_stage": stage},
            )

        return ActionResult(
            ok=False,
            action="click_see_availability",
            target="See availability",
            confidence=0.0,
            error_type=BrowserErrorType.ELEMENT_NOT_FOUND,
            error_detail="No See availability/select room control was found",
        )

    return ActionStep(
        name="click_see_availability",
        goal="Reveal room availability for the selected property",
        run=run,
    )


_BOOKING_ID_PATTERNS = (
    re.compile(r"(?:confirmation|booking|reservation)\s*(?:number|no\.?|id)?[:\s#-]+([A-Z0-9.-]{5,})", re.I),
    re.compile(r"[?&](?:bn|booking_number|reservation_id|confirmation)=([A-Z0-9.-]+)", re.I),
)


def _booking_id_from_text_or_url(text: str, url: str) -> str | None:
    for value in (url or "", text or ""):
        for pattern in _BOOKING_ID_PATTERNS:
            match = pattern.search(value)
            if match:
                return match.group(1)
    return None


class BookingAdapter(SiteAdapter):
    """Booking.com hotel adapter."""

    name = "booking"
    base_url = "https://www.booking.com"
    capabilities = SiteCapabilities(
        supports_checkout=True,
        requires_login=False,
        high_bot_detection=True,
        supports_autofill=False,
        supports_dry_run=True,
    )

    async def do_init(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        ctx["booking_init"] = True
        return type("Result", (), {
            "next_state": FlowState.SEARCH,
            "confidence": 1.0,
        })()

    async def do_search(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        if _looks_like_url(intent):
            target = intent if intent.startswith(("http://", "https://")) else f"https://{intent}"
            target = _with_booking_params(target, ctx)
            result = await goto(page, target, runtime)
            if not result.ok:
                raise BrowserError(
                    result.error_type or BrowserErrorType.NAVIGATION_FAILED,
                    result.error_detail or "Could not open Booking.com URL",
                    target,
                )
            ctx["booking_direct_url"] = True
            return type("Result", (), {
                "next_state": FlowState.SELECT,
                "confidence": result.confidence,
            })()

        result = await goto(page, _search_url(intent, ctx), runtime)
        if not result.ok:
            raise BrowserError(
                result.error_type or BrowserErrorType.NAVIGATION_FAILED,
                result.error_detail or "Could not open Booking.com search",
                page.url,
            )
        ctx["booking_search"] = True
        return type("Result", (), {
            "next_state": FlowState.SELECT,
            "confidence": result.confidence,
        })()

    async def do_select(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        if ctx.get("booking_direct_url") or "/hotel/" in (page.url or "").lower():
            ctx["booking_select"] = True
            return type("Result", (), {
                "next_state": FlowState.FORM_FILL,
                "confidence": 1.0,
            })()

        result = await ActionGraph([_click_first_property()]).execute(
            StepContext(page, intent, ctx, runtime)
        )
        if not getattr(result, "ok", False):
            raise BrowserError(
                getattr(result, "error_type", None) or BrowserErrorType.ELEMENT_NOT_FOUND,
                getattr(result, "error_detail", None) or "Could not open a Booking.com property",
                page.url,
            )
        ctx["booking_select"] = True
        return type("Result", (), {
            "next_state": FlowState.FORM_FILL,
            "confidence": getattr(result, "confidence", 0.8),
        })()

    async def do_form_fill(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        result = await ActionGraph([_click_see_availability()]).execute(
            StepContext(page, intent, ctx, runtime)
        )
        if not getattr(result, "ok", False):
            ctx["booking_availability_warning"] = getattr(result, "error_detail", None)
        ctx["booking_availability"] = True
        return type("Result", (), {
            "next_state": FlowState.REVIEW,
            "confidence": getattr(result, "confidence", 0.7) if result else 0.7,
        })()

    async def do_review(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        ctx["booking_review"] = True
        ctx["booking_stage"] = await classify_checkout_page(page)
        ctx["url"] = page.url
        return type("Result", (), {
            "next_state": FlowState.USER_CONFIRM,
            "confidence": 1.0,
        })()

    async def do_user_confirm(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        ctx["booking_user_handoff"] = True
        ctx["url"] = page.url
        return type("Result", (), {
            "next_state": FlowState.PAYMENT_HANDOFF,
            "confidence": 1.0,
        })()

    async def verify_goal_completed(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        ok = await self.is_confirmation_page(page)
        return type("Result", (), {
            "next_state": FlowState.DONE if ok else FlowState.ABORTED,
            "confidence": 1.0 if ok else 0.0,
        })()

    async def is_confirmation_page(self, page: Any) -> bool:
        return await _looks_like_confirmation_page(page)

    async def extract_receipt(self, page: Any) -> dict:
        url = page.url
        text = await _page_text(page)
        booking_id = _booking_id_from_text_or_url(text, url)
        scraped: dict[str, Any] = {}
        try:
            title = await page.title()
            scraped["page_title"] = title
        except Exception:
            pass

        money = re.search(r"(NPR|Rs\.?|US\$|USD|\$|EUR|GBP|€|£)\s*([0-9][0-9.,]*)", text, re.I)
        if money:
            scraped["currency"] = money.group(1).replace(".", "")
            raw_total = money.group(2).replace(",", "")
            try:
                scraped["total"] = float(raw_total)
            except ValueError:
                scraped["total"] = raw_total

        return {
            "source": "booking",
            "source_url": url,
            "order_id": booking_id,
            **scraped,
        }


__all__ = [
    "BookingAdapter",
    "STAGE_GUIDANCE",
    "classify_checkout_page",
    "classify_checkout_stage",
]
