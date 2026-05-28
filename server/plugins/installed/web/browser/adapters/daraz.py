"""Daraz Nepal adapter — search → product → Buy Now → payment handoff.

Architecture
────────────
Daraz is a commerce adapter. The flow drives the agent up to the
payment page; everything after that is the post-payment watcher's job
(see ``browser/commerce/watcher.py``). We never click "Place Order",
"Confirm Payment", or any equivalent — that's a hard contract enforced
by the state machine + the FORBIDDEN_INTENTS list.

Auth
────
Daraz requires login for Buy Now. The auth helper handles the one-time
sign-in; the persistent Chrome profile carries the session thereafter.

Why "Buy Now" not "Add to Cart"
───────────────────────────────
Buy Now is the express path: product page → checkout → payment. Cart
adds two extra steps (open cart, then click "Proceed to Checkout") for
zero benefit when the user is buying a single item via voice. Multi-
item carts are a future intent (``daraz_cart_checkout``).

Receipt extraction
──────────────────
After the user completes payment, Daraz lands on
``/order/success/`` (or similar). We expose ``is_confirmation_page``
and ``extract_receipt`` so the watcher can do its job without knowing
anything Daraz-specific. Selectors are best-effort and intentionally
loose — Daraz changes DOM frequently; a precise selector that breaks
in a month is worse than a generous one that misses one field.
"""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus, urlparse

from .base import SiteAdapter, SiteCapabilities
from ..action_graph import ActionGraph, ActionStep, StepContext
from ..auth import AuthSpec, ensure_signed_in
from ..errors import BrowserError, BrowserErrorType
from ..semantic import ActionResult, goto, wait_navigation
from ..state_machine import FlowState
from ..verification import GoalVerifier

logger = logging.getLogger(__name__)


# ── Auth ────────────────────────────────────────────────────────────────────
# Daraz is operated by Lazada — sessions show up as Lazada-style cookies
# (``lzd_*``, ``_m_h5_tk``). We list a couple of likely names; the
# substring match in is_signed_in catches variations.

DARAZ_AUTH = AuthSpec(
    name="daraz",
    home_url="https://www.daraz.com.np/",
    login_url="https://member.daraz.com.np/user/login.htm",
    # When signed in, Daraz shows the user name / account link in the
    # top navigation. The exact testid changes; we cover the two we've
    # seen + a generic /user/account/ anchor.
    signed_in_selector=(
        'a[href*="/user/account"], '
        '.lzd-user-info-name, '
        '[data-tracking="user_account"]'
    ),
    # Signed-out top bar shows LOGIN / SIGNUP prominently.
    signed_out_selectors=(
        'a[href*="/user/login"]',
        'a:has-text("LOGIN")',
        'a:has-text("Login")',
    ),
    cookie_indicators=("_m_h5_tk", "lzd_b_csg", "lzd_uti"),
    settle_ms=1000,
)


# ── Confirmation page recognition ──────────────────────────────────────────

# URL fragments that mean "the order went through". Loose on purpose —
# Daraz has shipped at least 3 different success URL shapes since 2022.
CONFIRMATION_URL_FRAGMENTS = (
    "/order/success",
    "/checkout/success",
    "/buyer/order/success",
    "/orderconfirmation",
)

# DOM signals as a fallback when the URL is ambiguous.
CONFIRMATION_DOM_SELECTORS = (
    'h1:has-text("Order Successful")',
    'h1:has-text("Order Placed")',
    'h2:has-text("Thank you")',
    'text="Please have this amount ready on delivery day"',
    'text="We\'ve sent you a confirmation email"',
    'text="To track the delivery of your order"',
    '[data-spm-anchor-id*="success"]',
)

CONFIRMATION_TEXT_MARKERS = (
    "please have this amount ready on delivery day",
    "we've sent you a confirmation email",
    "confirmation email",
    "to track the delivery of your order",
    "my account > my order",
    "continue shopping",
    "view order",
)


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
    if any(frag in url for frag in CONFIRMATION_URL_FRAGMENTS):
        return True

    for sel in CONFIRMATION_DOM_SELECTORS:
        try:
            if await page.locator(sel).count() > 0:
                return True
        except Exception:
            continue

    text = await _page_text(page)
    if not text:
        return False
    marker_count = sum(1 for marker in CONFIRMATION_TEXT_MARKERS if marker in text)
    return marker_count >= 2


# Daraz's checkout is a 4-stage funnel. Knowing which stage the user is
# on lets the watcher print accurate guidance instead of repeating
# "Finishing your payment?" while they're still typing their address.
def classify_checkout_stage(url: str) -> str:
    """Return one of: shipping | confirm | gateway | success | unknown."""
    u = (url or "").lower()
    if any(f in u for f in CONFIRMATION_URL_FRAGMENTS):
        return "success"
    # Daraz redirects to external payment gateways for card/eSewa/Khalti.
    if any(h in u for h in (
        "esewa.com.np", "khalti.com", "imepay.com", "fonepay.com",
        "/cashier", "/payment-process", "/pay/",
    )):
        return "gateway"
    if "/checkout" in u and "/shipping" not in u:
        return "confirm"
    if "/shipping" in u:
        return "shipping"
    return "unknown"


STAGE_GUIDANCE = {
    "shipping": (
        "Select or edit your shipping address if needed. Once delivery is selected, use Proceed to Pay."
    ),
    "shipping_ready": (
        "Your saved address and delivery option are ready. Click Proceed to Pay on the right side of Daraz."
    ),
    "confirm": (
        "Review your order, pick a payment method, then click Place Order."
    ),
    "gateway": (
        "Complete the payment in the gateway. eSewa / Khalti will ask you to log in again — that's their policy."
    ),
    "success": "Order placed! Capturing receipt...",
    "unknown": "Working through the Daraz checkout...",
}


_PROCEED_TO_PAY_SELECTORS = (
    'button:has-text("Proceed to Pay")',
    'button:has-text("PROCEED TO PAY")',
    'button:has-text("Proceed to pay")',
    '[class*="button"]:has-text("Proceed to Pay")',
)

_PAYMENT_REVIEW_SELECTORS = (
    'button:has-text("Place Order")',
    'button:has-text("PLACE ORDER")',
    'button:has-text("Pay Now")',
)


async def _any_visible(page: Any, selectors: tuple[str, ...]) -> bool:
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                return True
        except Exception:
            continue
    return False


async def classify_checkout_page(page: Any) -> str:
    """DOM-aware checkout stage classifier.

    Daraz often keeps the URL at ``/shipping`` even after a saved address
    and delivery option are ready. The URL-only classifier calls that
    ``shipping`` forever, which tells the user to save an address they
    already saved. This second pass looks for the real visible CTA.
    """
    if await _looks_like_confirmation_page(page):
        return "success"

    url_stage = classify_checkout_stage(getattr(page, "url", "") or "")
    if url_stage in {"success", "gateway"}:
        return url_stage

    if await _any_visible(page, _PAYMENT_REVIEW_SELECTORS):
        return "confirm"
    if await _any_visible(page, _PROCEED_TO_PAY_SELECTORS):
        return "shipping_ready"
    return url_stage


# ── URL helpers ────────────────────────────────────────────────────────────

def _looks_like_url(s: str) -> bool:
    """Heuristic: treat strings beginning with http(s):// or that contain
    ``daraz.com`` as direct product URLs to navigate to. Anything else
    is a search query."""
    if not s:
        return False
    low = s.strip().lower()
    return low.startswith(("http://", "https://")) or "daraz.com" in low


def _search_url(query: str) -> str:
    return f"https://www.daraz.com.np/catalog/?q={quote_plus(query)}"


# ── Variant auto-pick ──────────────────────────────────────────────────────

# Daraz product pages render variant selectors (size/color/storage) inside
# a container with class hint ``sku-selector`` or with the data-spm anchor
# containing ``sku``. Each option is a clickable element; disabled options
# carry the ``disabled`` class or aria-disabled="true". We grab the first
# non-disabled option in each group. Best-effort: a no-op if no variants
# exist (single-variant products like books) is correct behavior.

_VARIANT_GROUP_SELECTORS = (
    '.sku-selector',
    '[data-spm*="sku"]',
    '.sku-prop',
)
_OPTION_SELECTOR = (
    '.sku-variable-img-wrap:not(.disabled), '
    '.sku-variable-name:not(.disabled), '
    '.sku-property-text:not(.disabled):not(.sku-property-text-disabled), '
    'span.sku-variable:not(.disabled)'
)


async def _auto_pick_variants(page: Any) -> list[str]:
    """Click the first available option in each variant group on the
    current Daraz product page. Returns the list of option labels chosen
    (for logging / debugging). Empty list means no variants were present
    or none could be clicked safely."""
    chosen: list[str] = []
    for group_sel in _VARIANT_GROUP_SELECTORS:
        try:
            groups = page.locator(group_sel)
            count = await groups.count()
        except Exception as e:
            logger.debug("daraz variants: group %s lookup failed: %s", group_sel, e)
            continue

        for i in range(count):
            try:
                group = groups.nth(i)
                option = group.locator(_OPTION_SELECTOR).first
                if await option.count() == 0:
                    continue
                # Daraz uses image-only swatches for colors → text_content
                # is empty. Fall back to alt / aria-label / title so the
                # log line is meaningful.
                label = (await option.text_content() or "").strip()
                if not label:
                    label = await option.evaluate(
                        """el => (
                            el.getAttribute('aria-label') ||
                            el.getAttribute('title') ||
                            (el.querySelector('img') && el.querySelector('img').getAttribute('alt')) ||
                            ''
                        )"""
                    )
                    label = (label or "").strip() or "<unlabeled>"
                await option.scroll_into_view_if_needed(timeout=2_000)
                await option.click(timeout=3_000)
                chosen.append(label)
                # Small settle so the SKU state updates and the next group's
                # available options reflect the chosen one.
                await page.wait_for_timeout(300)
            except Exception as e:
                logger.debug("daraz variants: pick failed in group %d: %s", i, e)
                continue
        if chosen:
            # First container that yielded picks is enough — don't double-click.
            break
    if chosen:
        logger.info("daraz: auto-picked variants: %s", chosen)
    return chosen


_ORDER_ID_PATTERNS = (
    re.compile(r"[?&]tradeOrderId=([A-Za-z0-9-]+)"),
    re.compile(r"[?&]orderId=([A-Za-z0-9-]+)"),
    re.compile(r"/order/([A-Za-z0-9-]+)"),
)


def _order_id_from_url(url: str) -> str | None:
    for pat in _ORDER_ID_PATTERNS:
        m = pat.search(url or "")
        if m:
            return m.group(1)
    return None


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


async def _extract_order_info(page: Any) -> dict:
    """Read Daraz's structured checkout success payload.

    Daraz success pages push a JSON-ish object into ``window.dataLayer``:
    ``{ orderInfo: { order_id, orderItems: [...] } }``. That is much more
    reliable than scraping visible text and gives us product names, seller,
    SKU, quantity, and price for the confirmation email.
    """
    try:
        info = await page.evaluate(
            """
            () => {
                const layers = Array.isArray(window.dataLayer) ? window.dataLayer : [];
                for (const entry of layers) {
                    if (entry && entry.orderInfo && Array.isArray(entry.orderInfo.orderItems)) {
                        return entry.orderInfo;
                    }
                }
                return null;
            }
            """
        )
    except Exception as e:
        logger.debug("daraz extract: dataLayer orderInfo scrape failed: %s", e)
        info = None

    if not isinstance(info, dict):
        return {}

    items = []
    for raw in info.get("orderItems") or []:
        if not isinstance(raw, dict):
            continue
        name = _clean_text(raw.get("item_name") or raw.get("name"))
        if not name:
            continue
        qty = _clean_text(raw.get("quantity") or raw.get("qty") or "1")
        price = _clean_text(raw.get("price"))
        currency = _clean_text(info.get("currency") or info.get("currencyCode") or "Rs")
        item = {
            "name": name,
            "qty": qty,
            "price": price,
            "currency": currency,
            "seller": _clean_text(raw.get("seller_name")),
            "brand": _clean_text(raw.get("brand_name")),
            "sku": _clean_text(raw.get("simple_sku") or raw.get("sku_id")),
            "item_id": _clean_text(raw.get("item_id")),
        }
        # Remove empty optional fields so receipt.json stays tidy.
        items.append({k: v for k, v in item.items() if v not in ("", None)})

    out: dict = {}
    if info.get("order_id"):
        out["order_id"] = _clean_text(info.get("order_id"))
    if items:
        out["items"] = items
        out["item_count"] = len(items)
    return out


# ── Steps ──────────────────────────────────────────────────────────────────

def goto_daraz_search(query: str) -> ActionStep:
    async def run(ctx: StepContext):
        result = await goto(ctx.page, _search_url(query), ctx.runtime)
        try:
            # Wait for at least one product card to render. Daraz's search
            # SPA hydrates in two passes; the second one adds these cards.
            await ctx.page.wait_for_selector(
                '[data-qa-locator="product-item"], .box--ujueT, .gridItem--Yd0sa',
                timeout=10_000,
            )
        except Exception:
            # Continue regardless — the next step will report its own error.
            pass
        return result

    return ActionStep(
        name="goto_daraz_search",
        goal=f"Navigate to Daraz search for {query!r}",
        run=run,
    )


def click_first_product() -> ActionStep:
    """Open the first product card from a Daraz search results page.

    Strategy ladder, most-specific first. Daraz has shipped several
    distinct DOM trees for the search grid; we cover the two we've seen
    on .com.np and fall through to a structural anchor selector that
    works even if the data attributes change.
    """
    selectors = [
        '[data-qa-locator="product-item"] a[href*="/products/"]',
        '.box--ujueT a[href*="/products/"]',
        '.gridItem--Yd0sa a[href*="/products/"]',
        'a[href*="/products/"][href*="-i"]',  # Daraz product URLs are /products/<slug>-i<id>.html
    ]
    async def run(ctx: StepContext):
        for sel in selectors:
            try:
                loc = ctx.page.locator(sel).first
                await loc.wait_for(state="visible", timeout=5_000)
                href = await loc.get_attribute("href")
                await loc.scroll_into_view_if_needed(timeout=3_000)
                await loc.click(timeout=5_000)
                await wait_navigation(ctx.page)
                return ActionResult(
                    ok=True, action="click_first_product",
                    target=href or sel, confidence=0.9,
                    evidence={"strategy": sel},
                )
            except Exception as e:
                logger.debug("daraz: selector %s missed: %s", sel, e)
                continue
        return ActionResult(
            ok=False, action="click_first_product",
            target="product card", confidence=0.0,
            error_type=BrowserErrorType.ELEMENT_NOT_FOUND,
            error_detail="No Daraz product card matched any known selector",
        )

    return ActionStep(
        name="click_first_product",
        goal="Open first Daraz product result",
        run=run,
    )


def click_buy_now() -> ActionStep:
    """Click "Buy Now" on the product page.

    Daraz product pages have two CTAs side-by-side: "Add to Cart" (white)
    and "Buy Now" (orange). The Buy Now path skips the cart and goes
    straight to checkout — exactly what we want for a single-item buy.
    """
    selectors = [
        'button:has-text("Buy Now")',
        'button.pdp-button-theme--orange',          # legacy class
        '[data-spm-anchor-id*="buy_now"]',
        '.pdp-button--primary',                     # newer wrap
    ]
    async def run(ctx: StepContext):
        for sel in selectors:
            try:
                loc = ctx.page.locator(sel).first
                await loc.wait_for(state="visible", timeout=5_000)
                await loc.scroll_into_view_if_needed(timeout=3_000)
                await loc.click(timeout=5_000)
                # Buy Now redirects to checkout — may be SPA or full nav.
                await wait_navigation(ctx.page)
                return ActionResult(
                    ok=True, action="click_buy_now",
                    target=sel, confidence=0.9,
                    evidence={"strategy": sel},
                )
            except Exception as e:
                logger.debug("daraz: buy-now selector %s missed: %s", sel, e)
                continue
        return ActionResult(
            ok=False, action="click_buy_now",
            target="Buy Now", confidence=0.0,
            error_type=BrowserErrorType.ELEMENT_NOT_FOUND,
            error_detail=(
                "No Buy Now button found. The product may be out of stock, "
                "require variant selection first (size/color), or Daraz may "
                "have changed the button selector."
            ),
        )

    return ActionStep(
        name="click_buy_now",
        goal="Click Buy Now on the Daraz product page",
        run=run,
    )


# ── Adapter ────────────────────────────────────────────────────────────────

class DarazAdapter(SiteAdapter):
    """Daraz Nepal Buy Now adapter."""

    name = "daraz"
    base_url = "https://www.daraz.com.np"
    capabilities = SiteCapabilities(
        supports_checkout=True,
        requires_login=True,
        high_bot_detection=True,  # Lazada/Daraz is aggressive on bot detection
        supports_autofill=False,
        supports_dry_run=True,
    )

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def do_init(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        ok = await ensure_signed_in(page, DARAZ_AUTH, runtime, timeout_s=120.0)
        if not ok:
            raise BrowserError(
                BrowserErrorType.LOGIN_REQUIRED,
                "Daraz sign-in not completed within 2 minutes",
                page.url,
            )
        ctx["daraz_init"] = True
        return type("Result", (), {
            "next_state": FlowState.SEARCH, "confidence": 1.0,
        })()

    async def do_search(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        """Two intents possible. If ``intent`` looks like a URL we treat
        it as a direct product link (safer for tests). Otherwise we
        search and pick the first result.

        Direct URL is the recommended path for any voice-driven buy
        because "play first result" being a $200 cable is a real risk.
        """
        if _looks_like_url(intent):
            ctx["daraz_direct_url"] = True
            try:
                await page.goto(intent, wait_until="domcontentloaded", timeout=20_000)
            except Exception as e:
                raise BrowserError(
                    BrowserErrorType.NAVIGATION_FAILED,
                    f"Could not open Daraz product URL: {e}",
                    intent,
                )
            ctx["daraz_search"] = True
            # The state machine only allows SEARCH -> SELECT. We still
            # transition through SELECT but mark the context so do_select
            # knows we're already on the product page and shouldn't click
            # a search result.
            ctx["daraz_already_on_product"] = True
            return type("Result", (), {
                "next_state": FlowState.SELECT, "confidence": 1.0,
            })()

        graph = ActionGraph([goto_daraz_search(intent)])
        result = await graph.execute(StepContext(page, intent, ctx, runtime))
        ctx["daraz_search"] = True
        return type("Result", (), {
            "next_state": FlowState.SELECT,
            "confidence": getattr(result, "confidence", 0.9),
        })()

    async def do_select(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        # Direct-URL path skipped search entirely — we're already on the
        # product page, so do_select is a no-op transition rather than a
        # search-result click.
        if ctx.get("daraz_already_on_product"):
            ctx["daraz_select"] = True
            return type("Result", (), {
                "next_state": FlowState.FORM_FILL, "confidence": 1.0,
            })()

        graph = ActionGraph([click_first_product()])
        result = await graph.execute(StepContext(page, intent, ctx, runtime))
        if not getattr(result, "ok", True):
            raise BrowserError(
                getattr(result, "error_type", None) or BrowserErrorType.ELEMENT_NOT_FOUND,
                getattr(result, "error_detail", None) or "Could not open any product",
                page.url,
            )
        ctx["daraz_select"] = True
        return type("Result", (), {
            "next_state": FlowState.FORM_FILL,
            "confidence": getattr(result, "confidence", 0.9),
        })()

    async def do_form_fill(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        """Pick required variants (size/color/storage), then press Buy Now.

        Most Daraz products require at least one variant choice before
        Buy Now is enabled. We auto-pick the first available option in
        each variant group so the click succeeds. Caller can override
        later by exposing a ``variants`` field on the intent.
        """
        # Stage 1 — variant auto-pick (best-effort; safe to no-op).
        picked = await _auto_pick_variants(page)
        if picked:
            ctx["daraz_variants_picked"] = picked

        # Stage 2 — click Buy Now.
        graph = ActionGraph([click_buy_now()])
        result = await graph.execute(StepContext(page, intent, ctx, runtime))
        if not getattr(result, "ok", True):
            raise BrowserError(
                getattr(result, "error_type", None) or BrowserErrorType.ELEMENT_NOT_FOUND,
                getattr(result, "error_detail", None) or "Could not click Buy Now",
                page.url,
            )
        ctx["daraz_buy_now"] = True
        return type("Result", (), {
            "next_state": FlowState.REVIEW,
            "confidence": getattr(result, "confidence", 0.9),
        })()

    async def do_review(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        """We're on the checkout/review page. Let the SPA hydrate so the
        next state's ``_post_step`` can run ``detect_payment_page`` against
        a fully-rendered DOM, then advance the state machine.

        We DO NOT click anything here. Address, payment-method choice,
        and the final 'Place Order' click are all the user's job.
        """
        try:
            await page.wait_for_timeout(1500)
        except Exception:
            pass
        ctx["daraz_review"] = True
        return type("Result", (), {
            "next_state": FlowState.USER_CONFIRM, "confidence": 1.0,
        })()

    async def do_user_confirm(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        """Hand off to the user.

        We explicitly transition to PAYMENT_HANDOFF as a backstop in case
        ``detect_payment_page`` didn't flip us already (some Daraz layouts
        don't render the payment-method text until you scroll). The flow
        then terminates and our caller spawns the receipt watcher.
        """
        ctx["daraz_user_confirm"] = True
        return type("Result", (), {
            "next_state": FlowState.PAYMENT_HANDOFF, "confidence": 1.0,
        })()

    # Goal verification is only reached on the DONE leg. For commerce we
    # almost never get here (PAYMENT_HANDOFF is terminal), but if we did
    # the criterion is: are we on a confirmation page?
    async def verify_goal_completed(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        ok = await self.is_confirmation_page(page)
        return type("Result", (), {
            "next_state": FlowState.DONE if ok else FlowState.ABORTED,
            "confidence": 1.0 if ok else 0.0,
        })()

    # ── Commerce-adapter contract (used by watcher.py) ────────────────────

    async def is_confirmation_page(self, page: Any) -> bool:
        return await _looks_like_confirmation_page(page)

    async def extract_receipt(self, page: Any) -> dict:
        """Scrape what we can from the order-success page.

        Field detection is generous — we'd rather return a partial record
        with a screenshot than fail the whole capture because one selector
        changed. The watcher saves the page HTML separately so any field
        we missed can be re-parsed offline later.
        """
        url = page.url
        order_id = _order_id_from_url(url)

        # Try a couple of common DOM places. Wrapped in try/except since
        # any of them may not exist on a given Daraz layout version.
        scraped: dict = {}
        order_info = await _extract_order_info(page)
        if order_info.get("order_id"):
            order_id = order_info["order_id"]
        for key, value in order_info.items():
            if key != "order_id":
                scraped[key] = value

        # Order id from DOM if URL didn't carry it.
        if not order_id:
            try:
                txt = await page.evaluate(
                    """
                    () => {
                        const m = document.body.innerText.match(/Order\\s*(?:No\\.?|Number|ID)[:\\s#]*([A-Za-z0-9-]+)/i);
                        return m ? m[1] : null;
                    }
                    """
                )
                if txt:
                    order_id = str(txt)
            except Exception:
                pass

        # Total + currency — Daraz Nepal uses "Rs." or "NPR".
        try:
            money = await page.evaluate(
                """
                () => {
                    const re = /(NPR|Rs\\.?|₨)\\s*([0-9.,]+)/i;
                    const m = document.body.innerText.match(re);
                    return m ? {currency: m[1].replace(/[.\\s₨]/g, '') || 'NPR', total: m[2]} : null;
                }
                """
            )
            if money:
                scraped["currency"] = money.get("currency") or "NPR"
                # Strip thousands separators, keep decimal.
                raw_total = str(money.get("total") or "").replace(",", "")
                try:
                    scraped["total"] = float(raw_total)
                except ValueError:
                    scraped["total"] = raw_total
        except Exception as e:
            logger.debug("daraz extract: total scrape failed: %s", e)

        # If the success page hides the total from visible text but the
        # structured order payload has line prices, still give the email a
        # useful total and currency.
        items = order_info.get("items") or []
        if items and not scraped.get("currency"):
            for item in items:
                if item.get("currency"):
                    scraped["currency"] = item["currency"]
                    break
        if items and "total" not in scraped:
            total = 0.0
            found_price = False
            for item in items:
                raw_price = str(item.get("price") or "").replace(",", "")
                match = re.search(r"\d+(?:\.\d+)?", raw_price)
                if not match:
                    continue
                try:
                    total += float(match.group(0))
                    found_price = True
                except ValueError:
                    continue
            if found_price:
                scraped["total"] = total

        # Page title is a useful debugging anchor.
        try:
            scraped["page_title"] = await page.title()
        except Exception:
            pass

        return {
            "source": "daraz",
            "source_url": url,
            "order_id": order_id,
            **scraped,
        }


__all__ = ["DarazAdapter", "DARAZ_AUTH"]
