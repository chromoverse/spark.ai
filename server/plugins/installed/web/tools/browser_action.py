"""
browser_action — transactional browser tool.

This tool exists because retrieval and action belong to *different*
subsystems (per the retrieval-architecture guide). ``web_research`` finds
entities; ``browser_action`` does something *with* them — book a room,
buy a product, play a movie. It must never be used to search.

Contract
────────
Always takes a verb (``action``) plus either a structured entity (the
exact dict returned by ``web_research``) or an explicit URL / title.
Never a freeform query.

Shipped handlers
────────────────
  open_url        → opens entity.booking_url / entity.maps_url / website /
                    the explicit ``url`` arg in the user's default browser.
                    Honest minimal handler — works today on every site.

  play_media      → opens a YouTube search for ``title`` (or the entity
                    name). Real automation later if the user wants
                    auto-play / Netflix etc.

Stubbed handlers (return graceful "opening URL for manual completion")
  book_hotel      → opens the hotel's booking_url; user finishes the flow.
  reserve_table   → opens the restaurant's booking_url / Google Maps.
  book_ticket     → opens the event's booking_url.

Automated handlers
  buy_product     → drives Daraz to checkout, waits while the user pays,
                    then captures/emails the receipt when confirmation appears.

Real automation (Playwright/nodriver flows with auth) will replace these
stubs as we add per-site adapters. The contract above doesn't change —
upgrading a handler just means swapping its body.

Execution
─────────
Runs on the server (the desktop user's machine in DESKTOP mode). Uses
``webbrowser.open`` via ``asyncio.to_thread`` so the OS-level browser
launch never blocks the event loop.
"""

from __future__ import annotations

import asyncio
import logging
import webbrowser
from typing import Any, Awaitable, Callable, Dict, Optional
from urllib.parse import quote_plus, urlparse

from app.plugins.tools.tool_base import BaseTool, ToolOutput

logger = logging.getLogger(__name__)


# ── Commerce site routing ────────────────────────────────────────────────────
# Map a hostname substring to the adapter intent registered in
# server/plugins/installed/web/browser/tool.py. The default (no host signal)
# is picked at call time from the user's country.

_HOST_TO_INTENT: Dict[str, str] = {
    "daraz.com.np":  "daraz_buy",
    "daraz.":        "daraz_buy",   # daraz.com, daraz.lk, etc.
    "amazon.":       "amazon_buy",  # amazon.com, amazon.in, amazon.co.uk
}

# Country-default fallback when the entity carries no usable host. The
# project is Nepal-centric so NP → Daraz, otherwise Amazon. Anything not
# in this map collapses to the previous behaviour (daraz_buy via the
# generic buy_product registration).
_COUNTRY_DEFAULT_INTENT: Dict[str, str] = {
    "NP": "daraz_buy",
    "IN": "amazon_buy",
    "US": "amazon_buy",
    "UK": "amazon_buy",
    "GB": "amazon_buy",
}


def _pick_buy_intent(
    *,
    entity: Optional[Dict[str, Any]],
    url: Optional[str],
    country_code: Optional[str],
) -> str:
    """Pick the BrowserAgentTool intent that should drive this purchase.

    Order of precedence:
      1. explicit ``url`` host
      2. ``entity.buy_url`` / ``source_url`` / ``website`` host
      3. country default
      4. ``buy_product`` (legacy generic, currently DarazAdapter)
    """
    candidates = []
    if url:
        candidates.append(url)
    if entity:
        for key in ("buy_url", "source_url", "website"):
            v = entity.get(key)
            if isinstance(v, str) and v:
                candidates.append(v)

    for u in candidates:
        try:
            host = (urlparse(u).netloc or "").lower().removeprefix("www.")
        except Exception:
            continue
        if not host:
            continue
        for needle, intent in _HOST_TO_INTENT.items():
            if needle in host:
                return intent

    if country_code:
        cc = country_code.strip().upper()
        if cc in _COUNTRY_DEFAULT_INTENT:
            return _COUNTRY_DEFAULT_INTENT[cc]

    return "buy_product"


def _country_code_from_params(params: Dict[str, Any]) -> Optional[str]:
    """Pull a country code from the action params if upstream provided one.

    SQH can bind it from the ``current_location`` tool's ``country_code``
    so the handler doesn't need to call out to geo-IP itself.
    """
    if not params:
        return None
    for key in ("country_code", "country"):
        v = params.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


# ── Action registry ──────────────────────────────────────────────────────────
# Mapping action verb → async handler. Adding a new action = one entry.
# Each handler takes the resolved ``BrowserActionContext`` and returns the
# data dict that will surface in ToolOutput.

class BrowserActionContext:
    """Normalized inputs the handlers consume."""
    __slots__ = ("action", "entity", "url", "title", "params")

    def __init__(
        self,
        action: str,
        entity: Optional[Dict[str, Any]],
        url: Optional[str],
        title: Optional[str],
        params: Dict[str, Any],
    ) -> None:
        self.action = action
        self.entity = entity or {}
        self.url = url
        self.title = title
        self.params = params or {}


_Handler = Callable[[BrowserActionContext], Awaitable[Dict[str, Any]]]


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _open_browser(url: str) -> bool:
    """Launch the OS default browser pointed at ``url``. Non-blocking."""
    try:
        return bool(await asyncio.to_thread(webbrowser.open, url))
    except Exception as exc:
        logger.warning("browser_action: webbrowser.open(%r) failed: %s", url, exc)
        return False


def _entity_url(entity: Dict[str, Any], *, prefer: tuple = ("booking_url", "maps_url", "website", "buy_url", "menu_url", "source_url")) -> Optional[str]:
    """Pull the most useful URL off an entity for this action."""
    for key in prefer:
        v = entity.get(key)
        if v and isinstance(v, str):
            return v
    return None


def _maps_search_url(name: str, address: Optional[str] = None) -> str:
    parts = [p for p in (name, address) if p]
    q = quote_plus(", ".join(parts))
    return f"https://www.google.com/maps/search/?api=1&query={q}"


def _url_host(value: Optional[str]) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    text = value.strip()
    try:
        parsed = urlparse(text if "://" in text else f"https://{text}")
    except Exception:
        return ""
    return (parsed.netloc or "").lower().removeprefix("www.")


def _is_booking_site_url(value: Optional[str]) -> bool:
    host = _url_host(value)
    return host == "booking.com" or host.endswith(".booking.com")


def _is_map_or_directory_url(value: Optional[str]) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    text = value.strip()
    try:
        parsed = urlparse(text if "://" in text else f"https://{text}")
    except Exception:
        return False
    host = (parsed.netloc or "").lower().removeprefix("www.")
    path = (parsed.path or "").lower()
    if host == "openstreetmap.org" or host.endswith(".openstreetmap.org"):
        return True
    if host == "osm.org" or host.endswith(".osm.org"):
        return True
    if host in {"maps.app.goo.gl", "goo.gl"}:
        return True
    if ("google." in host or host == "google.com") and "/maps" in path:
        return True
    return False


def _hotel_booking_query(entity: Dict[str, Any], title: Optional[str]) -> Optional[str]:
    parts = []
    seen = set()
    for value in (
        title,
        entity.get("name"),
        entity.get("address"),
        entity.get("location"),
        entity.get("city"),
        entity.get("country"),
    ):
        if not isinstance(value, str):
            continue
        text = value.strip()
        key = text.lower()
        if not text or key in seen:
            continue
        parts.append(text)
        seen.add(key)
    return ", ".join(parts) if parts else None


def _hotel_direct_booking_url(entity: Dict[str, Any], explicit_url: Optional[str]) -> Optional[str]:
    for value in (explicit_url, entity.get("booking_url")):
        if isinstance(value, str) and _is_booking_site_url(value):
            return value.strip()
    return None


def _hotel_manual_booking_url(entity: Dict[str, Any], explicit_url: Optional[str]) -> Optional[str]:
    for value in (explicit_url, entity.get("booking_url"), entity.get("website")):
        if not isinstance(value, str) or not value.strip():
            continue
        if _is_map_or_directory_url(value):
            continue
        return value.strip()
    return None


def _booking_search_url(query: str) -> str:
    return f"https://www.booking.com/searchresults.html?ss={quote_plus(query)}"


def _youtube_search_url(title: str) -> str:
    return f"https://www.youtube.com/results?search_query={quote_plus(title)}"


# ── Handlers ─────────────────────────────────────────────────────────────────

async def _handle_open_url(ctx: BrowserActionContext) -> Dict[str, Any]:
    """Open whatever URL the entity / ctx exposes. Generic 'do something' button."""
    url = ctx.url or _entity_url(ctx.entity) or (
        _maps_search_url(ctx.entity.get("name", ""), ctx.entity.get("address"))
        if ctx.entity.get("name") else None
    )
    if not url:
        return {"opened": False, "reason": "no URL on entity and none provided"}
    ok = await _open_browser(url)
    return {
        "opened": ok,
        "url": url,
        "action": "open_url",
        "message": f"Opened {url}" if ok else "Browser launch failed",
    }


async def _handle_play_media(ctx: BrowserActionContext) -> Dict[str, Any]:
    """Delegate to BrowserAgentTool if available, else fallback to URL open."""
    title = ctx.title or ctx.entity.get("name") or ctx.entity.get("title")
    if not title:
        return {"opened": False, "reason": "no title or entity name to play"}
    
    # Try automated flow first
    try:
        from ..browser.tool import BrowserAgentTool
        tool = BrowserAgentTool()
        result = await tool._execute({
            "intent": "youtube_play",
            "query": str(title),
            "dry_run": False
        })
        if result.success:
            return {
                "opened": True,
                "automated": True,
                "action": "play_media",
                "title": str(title),
                "message": f"Automated YouTube play for {title!r}",
                "data": result.data
            }
    except Exception as e:
        logger.warning("BrowserAgentTool failed, falling back to URL open: %s", e)
    
    # Fallback to URL open
    url = ctx.url or _youtube_search_url(str(title))
    ok = await _open_browser(url)
    return {
        "opened": ok,
        "url": url,
        "action": "play_media",
        "title": str(title),
        "automated": False,
        "message": f"Opened YouTube for {title!r}" if ok else "Browser launch failed",
    }


async def _handle_play_music(ctx: BrowserActionContext) -> Dict[str, Any]:
    """Play a track/album/playlist on Spotify Web.

    Same shape as play_media (YouTube) but routes to the spotify_play
    adapter. Requires sign-in the first time — the auth helper drives
    that interactively, then the persistent profile carries the session.
    """
    title = ctx.title or ctx.entity.get("name") or ctx.entity.get("title")
    if not title:
        return {"opened": False, "reason": "no title or entity name to play"}

    try:
        from ..browser.tool import BrowserAgentTool
        result = await BrowserAgentTool()._execute({
            "intent": "spotify_play",
            "query": str(title),
            "dry_run": False,
        })
        if result.success:
            return {
                "opened": True,
                "automated": True,
                "action": "play_music",
                "title": str(title),
                "message": f"Playing {title!r} on Spotify",
                "data": result.data,
            }
        # Adapter ran but didn't succeed — pass the typed reason up rather
        # than silently falling back. Sign-in timeout / no results / etc.
        return {
            "opened": False,
            "automated": True,
            "action": "play_music",
            "title": str(title),
            "reason": result.error or "Spotify flow did not complete",
            "data": result.data,
        }
    except Exception as e:
        logger.warning("Spotify adapter failed, falling back to URL open: %s", e)

    url = f"https://open.spotify.com/search/{quote_plus(str(title))}"
    ok = await _open_browser(url)
    return {
        "opened": ok,
        "automated": False,
        "url": url,
        "action": "play_music",
        "title": str(title),
        "message": f"Opened Spotify search for {title!r}" if ok else "Browser launch failed",
    }


async def _handle_buy_product(ctx: BrowserActionContext) -> Dict[str, Any]:
    """Real ``buy_product`` flow — drives the Daraz adapter to the
    payment page, then hands off to the user and spawns the post-payment
    receipt watcher.

    By default this waits for the watcher to capture a receipt or time
    out, so Spark stays alive while the user completes the browser-only
    checkout steps. Callers can pass ``params.wait_for_receipt=false``
    to restore the old fire-and-forget behavior.
    """
    title = ctx.title or (ctx.entity.get("name") if ctx.entity else None) or (ctx.entity.get("title") if ctx.entity else None)
    target_url = ctx.url or _entity_url(ctx.entity, prefer=("buy_url", "source_url", "website"))
    target = target_url or title
    if not target:
        return {"opened": False, "reason": "no product URL or name/title provided"}
    display_title = str(title or target)

    wait_for_receipt = bool(ctx.params.get("wait_for_receipt", True))
    try:
        watch_timeout_s = float(ctx.params.get("watch_timeout_s", ctx.params.get("timeout_s", 600.0)))
    except (TypeError, ValueError):
        watch_timeout_s = 600.0

    try:
        from ..browser.tool import BrowserAgentTool, _ADAPTERS
        from ..browser.commerce.watcher import start_receipt_watch

        # Pick the right adapter from the entity's host (daraz/amazon).
        # Falls back to the country default, then to the legacy generic
        # ``buy_product`` registration if neither signal is present.
        buy_intent = _pick_buy_intent(
            entity=ctx.entity,
            url=ctx.url,
            country_code=_country_code_from_params(ctx.params),
        )

        result = await BrowserAgentTool()._execute({
            "intent": buy_intent,
            "query": str(target),
            "dry_run": False,
            # approve_payment=True here means "I expect this flow to reach
            # the payment page, treat that as success, and DO NOT abort".
            # It is NOT a permission to submit a payment form — that
            # contract is enforced inside the state machine (see the
            # comment in state_machine.py around PAYMENT_HANDOFF). The
            # flag is misnamed historically; the docstring there spells
            # out the actual semantics.
            "approve_payment": True,
        })

        # The agent landed at payment_handoff → spawn the watcher.
        state = (result.data or {}).get("state")
        if state == "payment_handoff":
            adapter_cls = _ADAPTERS.get(buy_intent) or _ADAPTERS.get("buy_product")
            adapter = adapter_cls() if adapter_cls else None
            watch_task = None
            if adapter is not None:
                watch_task = start_receipt_watch(
                    adapter,
                    timeout_s=watch_timeout_s,
                    poll_every_s=2.0,
                    reminder_every_s=30.0,
                )
            if wait_for_receipt and watch_task is not None:
                watch_result = await watch_task
                saved = watch_result.saved
                receipt = {
                    "captured": watch_result.captured,
                    "timed_out": watch_result.timed_out,
                    "duration_s": watch_result.duration_s,
                    "email": watch_result.email,
                    "error": watch_result.error,
                }
                if saved is not None:
                    receipt.update({
                        "dir": str(saved.dir),
                        "receipt_path": str(saved.receipt_path),
                        "screenshot_path": str(saved.screenshot_path) if saved.screenshot_path else None,
                        "html_path": str(saved.html_path) if saved.html_path else None,
                        "order_id": saved.data.get("order_id"),
                        "total": saved.data.get("total"),
                        "currency": saved.data.get("currency"),
                    })
                if watch_result.captured:
                    stage = "receipt_captured"
                    message = (
                        f"Receipt captured for {display_title!r}. "
                        "It was saved to disk and email delivery was attempted."
                    )
                elif watch_result.timed_out:
                    stage = "watch_timeout"
                    message = (
                        f"Timed out waiting for Daraz confirmation for {display_title!r}. "
                        "If you completed payment, check your Daraz orders."
                    )
                else:
                    stage = "watch_error"
                    message = f"Receipt watcher stopped for {display_title!r}: {watch_result.error}"
                return {
                    "opened": True,
                    "automated": True,
                    "action": "buy_product",
                    "title": display_title,
                    "stage": stage,
                    "message": message,
                    "watching": False,
                    "receipt": receipt,
                    "data": result.data,
                }
            return {
                "opened": True,
                "automated": True,
                "action": "buy_product",
                "title": display_title,
                "stage": "awaiting_payment",
                "message": (
                    f"Reached payment page for {display_title!r}. Complete payment in the browser — "
                    "the receipt will be saved to disk and emailed automatically."
                ),
                "watching": watch_task is not None,
                "data": result.data,
            }

        # Flow succeeded without payment (shouldn't normally happen for
        # buy_product) — surface as best-effort success.
        if result.success:
            return {
                "opened": True,
                "automated": True,
                "action": "buy_product",
                "title": display_title,
                "stage": state or "done",
                "message": f"Flow completed in state {state!r} for {display_title!r}",
                "data": result.data,
            }

        return {
            "opened": False,
            "automated": True,
            "action": "buy_product",
            "title": display_title,
            "reason": result.error or "buy_product flow failed",
            "data": result.data,
        }
    except Exception as e:
        logger.warning("buy_product adapter failed, falling back to URL open: %s", e)

    # Fallback: open a search page so the user can do it manually. Pick the
    # search host the same way we picked the adapter, so Amazon entities
    # don't get redirected to a Daraz search and vice versa.
    fallback_intent = _pick_buy_intent(
        entity=ctx.entity,
        url=ctx.url,
        country_code=_country_code_from_params(ctx.params),
    )
    if target_url:
        url = target_url
        site_label = "the product page"
    elif fallback_intent == "amazon_buy":
        url = f"https://www.amazon.com/s?k={quote_plus(str(display_title))}"
        site_label = "Amazon search"
    else:
        url = f"https://www.daraz.com.np/catalog/?q={quote_plus(str(display_title))}"
        site_label = "Daraz search"
    ok = await _open_browser(url)
    return {
        "opened": ok,
        "automated": False,
        "url": url,
        "action": "buy_product",
        "title": display_title,
        "message": f"Opened {site_label} for {display_title!r}" if ok else "Browser launch failed",
    }


async def _handle_book_hotel(ctx: BrowserActionContext) -> Dict[str, Any]:
    """Drive Booking.com to a safe handoff, then watch for confirmation.

    The adapter can open a hotel/search result and reveal room
    availability. It never clicks the final irreversible booking/charge
    button; once the user is in the Booking.com flow, the receipt watcher
    waits for a confirmation page and captures it.
    """
    title = (
        ctx.title
        or (ctx.entity.get("name") if ctx.entity else None)
        or (ctx.entity.get("title") if ctx.entity else None)
    )
    direct_booking_url = _hotel_direct_booking_url(ctx.entity, ctx.url)
    manual_booking_url = _hotel_manual_booking_url(ctx.entity, ctx.url)
    hotel_query = _hotel_booking_query(ctx.entity, title)
    target = direct_booking_url or hotel_query
    if not target:
        if manual_booking_url:
            manual_title = str(title or manual_booking_url)
            ok = await _open_browser(manual_booking_url)
            return {
                "opened": ok,
                "automated": False,
                "url": manual_booking_url,
                "action": "book_hotel",
                "title": manual_title,
                "message": (
                    f"Opened hotel booking page for {manual_title!r}"
                    if ok else "Browser launch failed"
                ),
            }
        return {"opened": False, "reason": "no hotel booking URL or name/title provided"}
    display_title = str(title or target)

    wait_for_confirmation = bool(ctx.params.get("wait_for_confirmation", True))
    try:
        watch_timeout_s = float(ctx.params.get("watch_timeout_s", ctx.params.get("timeout_s", 900.0)))
    except (TypeError, ValueError):
        watch_timeout_s = 900.0

    try:
        from ..browser.tool import BrowserAgentTool, _ADAPTERS
        from ..browser.commerce.watcher import start_receipt_watch

        result = await BrowserAgentTool()._execute({
            "intent": "book_hotel",
            "query": str(target),
            "entity": ctx.entity,
            "params": {**ctx.params, "hotel_search_query": hotel_query},
            "dry_run": False,
            "approve_payment": True,
        })

        state = (result.data or {}).get("state")
        if state == "payment_handoff":
            adapter_cls = _ADAPTERS.get("book_hotel")
            adapter = adapter_cls() if adapter_cls else None
            watch_task = None
            if adapter is not None:
                watch_task = start_receipt_watch(
                    adapter,
                    timeout_s=watch_timeout_s,
                    poll_every_s=2.0,
                    reminder_every_s=30.0,
                    desktop_reminder_every_s=10.0,
                    desktop_reminder_max_s=120.0,
                )

            if wait_for_confirmation and watch_task is not None:
                watch_result = await watch_task
                saved = watch_result.saved
                confirmation = {
                    "captured": watch_result.captured,
                    "timed_out": watch_result.timed_out,
                    "duration_s": watch_result.duration_s,
                    "email": watch_result.email,
                    "error": watch_result.error,
                }
                if saved is not None:
                    confirmation.update({
                        "dir": str(saved.dir),
                        "receipt_path": str(saved.receipt_path),
                        "screenshot_path": str(saved.screenshot_path) if saved.screenshot_path else None,
                        "html_path": str(saved.html_path) if saved.html_path else None,
                        "booking_id": saved.data.get("order_id"),
                        "total": saved.data.get("total"),
                        "currency": saved.data.get("currency"),
                    })

                if watch_result.captured:
                    stage = "booking_confirmation_captured"
                    message = (
                        f"Booking confirmation captured for {display_title!r}. "
                        "It was saved to disk and email delivery was attempted."
                    )
                elif watch_result.timed_out:
                    stage = "watch_timeout"
                    message = (
                        f"Timed out waiting for Booking.com confirmation for {display_title!r}. "
                        "If you completed the booking, check your Booking.com account/email."
                    )
                else:
                    stage = "watch_error"
                    message = f"Booking watcher stopped for {display_title!r}: {watch_result.error}"

                return {
                    "opened": True,
                    "automated": True,
                    "action": "book_hotel",
                    "title": display_title,
                    "stage": stage,
                    "message": message,
                    "watching": False,
                    "confirmation": confirmation,
                    "data": result.data,
                }

            return {
                "opened": True,
                "automated": True,
                "action": "book_hotel",
                "title": display_title,
                "stage": "awaiting_booking_completion",
                "message": (
                    f"Reached Booking.com handoff for {display_title!r}. "
                    "Complete the booking in the browser; Spark will capture the confirmation."
                ),
                "watching": watch_task is not None,
                "data": result.data,
            }

        if result.success:
            return {
                "opened": True,
                "automated": True,
                "action": "book_hotel",
                "title": display_title,
                "stage": state or "done",
                "message": f"Booking flow completed in state {state!r} for {display_title!r}",
                "data": result.data,
            }

        fallback_url = manual_booking_url or _booking_search_url(hotel_query or display_title)
        ok = await _open_browser(fallback_url)
        return {
            "opened": ok,
            "automated": False,
            "url": fallback_url,
            "action": "book_hotel",
            "title": display_title,
            "reason": result.error or "book_hotel flow failed",
            "message": (
                f"Opened fallback booking page for {display_title!r}"
                if ok else "Browser launch failed"
            ),
            "data": result.data,
        }
    except Exception as e:
        logger.warning("book_hotel adapter failed, falling back to URL open: %s", e)

    url = manual_booking_url or _booking_search_url(hotel_query or display_title)
    site_label = "hotel site" if manual_booking_url else "Booking.com"
    ok = await _open_browser(url)
    return {
        "opened": ok,
        "automated": False,
        "url": url,
        "action": "book_hotel",
        "title": display_title,
        "message": f"Opened {site_label} for {display_title!r}" if ok else "Browser launch failed",
    }


async def _handle_stub_booking(ctx: BrowserActionContext) -> Dict[str, Any]:
    """Stub for reserve_table / book_ticket.

    Opens whatever booking URL the entity exposes so the user can
    complete the flow manually. Real automation comes later.
    """
    url = ctx.url or _entity_url(ctx.entity) or (
        _maps_search_url(ctx.entity.get("name", ""), ctx.entity.get("address"))
        if ctx.entity.get("name") else None
    )
    if not url:
        return {
            "opened": False,
            "automated": False,
            "action": ctx.action,
            "reason": (
                f"{ctx.action}: no booking URL on entity. Pass `url` explicitly or "
                "retrieve the entity again so the provider can fill it in."
            ),
        }
    ok = await _open_browser(url)
    return {
        "opened": ok,
        "automated": False,  # explicit: this is open-and-let-user-finish
        "url": url,
        "action": ctx.action,
        "message": (
            f"Opened {url} for manual completion. "
            f"Automated {ctx.action} flow not yet implemented — the user finishes the flow."
        ),
    }


_HANDLERS: Dict[str, _Handler] = {
    "open_url":      _handle_open_url,
    "play_media":    _handle_play_media,
    "play_music":    _handle_play_music,
    "buy_product":   _handle_buy_product,
    "book_hotel":    _handle_book_hotel,
    # Remaining stubs share one impl — distinct action names so future
    # per-flow automation can override them individually without touching
    # callers.
    "reserve_table": _handle_stub_booking,
    "book_ticket":   _handle_stub_booking,
}


# ── Tool ─────────────────────────────────────────────────────────────────────

class BrowserActionTool(BaseTool):
    """Perform a transactional action in the user's browser.

    Use cases:
      • Open a booking page for a hotel/restaurant returned by web_research
      • Play a movie / video by title
      • (Future) Drive an authenticated booking flow end-to-end

    Never use this to *find* things — that's web_research's job.
    """

    TOOL_DESCRIPTION = (
        "Perform a transactional action in the user's browser: open a booking "
        "page, buy a product, reserve a table, play a movie/video. Takes a "
        "verb (action) plus a structured entity (from web_research) or an "
        "explicit URL/title. Not a search tool — use web_research first."
    )
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA: Dict[str, Any] = {
        "action": {
            "type": "string",
            "required": True,
            "enum": list(_HANDLERS.keys()),
            "description": (
                "open_url | play_media (YouTube) | play_music (Spotify) | "
                "book_hotel | buy_product | reserve_table | book_ticket"
            ),
        },
        "entity": {
            "type": "object",
            "required": False,
            "description": (
                "Structured entity from web_research (hotel, restaurant, "
                "movie, …). Provides the URL(s) and metadata the action needs."
            ),
        },
        "url": {
            "type": "string",
            "required": False,
            "description": "Explicit URL override. Wins over anything on the entity.",
        },
        "title": {
            "type": "string",
            "required": False,
            "description": "For play_media: title to search for if no entity is given.",
        },
        "params": {
            "type": "object",
            "required": False,
            "description": "Action-specific options (dates, quantity, etc.). Reserved for future automated flows.",
        },
    }
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {
            "action":    {"type": "string"},
            "opened":    {"type": "boolean"},
            "url":       {"type": "string", "optional": True},
            "title":     {"type": "string", "optional": True},
            "automated": {"type": "boolean", "optional": True},
            "message":   {"type": "string", "optional": True},
            "reason":    {"type": "string", "optional": True},
        },
        "error": {"type": "string"},
    }
    EXAMPLES = [
        {"user_utterance": "book that hotel"},
        {"user_utterance": "play interstellar"},
        {"user_utterance": "play arctic monkeys on spotify"},
    ]
    SEMANTIC_TAGS = ["browser", "action", "book", "buy", "play", "open"]
    TOOL_CATEGORY = "browser_action"

    def get_tool_name(self) -> str:
        return "browser_action"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        action = str(self.get_input(inputs, "action", "") or "").strip().lower()
        if not action:
            return ToolOutput(success=False, data={}, error="`action` is required")
        handler = _HANDLERS.get(action)
        if handler is None:
            return ToolOutput(
                success=False, data={},
                error=f"Unknown action {action!r}. Valid: {sorted(_HANDLERS)}",
            )

        ctx = BrowserActionContext(
            action=action,
            entity=self.get_input(inputs, "entity", None),
            url=self.get_input(inputs, "url", None),
            title=self.get_input(inputs, "title", None),
            params=self.get_input(inputs, "params", {}) or {},
        )

        try:
            result = await handler(ctx)
        except Exception as exc:
            logger.exception("browser_action: handler %s crashed", action)
            return ToolOutput(success=False, data={"action": action}, error=str(exc))

        # ``opened: false`` is still a "successful" tool call from the
        # orchestrator's perspective — the tool did its job and reported
        # honestly. Only handler crashes / missing inputs are failures.
        return ToolOutput(success=True, data=result)


__all__ = ["BrowserActionTool"]
