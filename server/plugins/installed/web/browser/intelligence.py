"""Page classifier and detection predicates."""
from enum import Enum
from typing import Any, Optional
import re


class PageIntent(str, Enum):
    UNKNOWN = "unknown"
    LOGIN = "login"
    SEARCH_RESULTS = "search_results"
    DETAIL = "detail"
    CART = "cart"
    CHECKOUT = "checkout"
    PAYMENT = "payment"
    CONFIRMATION = "confirmation"
    MODAL = "modal"
    CAPTCHA = "captcha"
    ERROR = "error"


async def classify_page(page: Any) -> PageIntent:
    """Classify page intent based on content."""
    try:
        url = page.url.lower()
        title = (await page.title()).lower()
        
        # Check URL patterns first
        if any(p in url for p in ["login", "signin", "sign-in", "auth"]):
            return PageIntent.LOGIN
        if any(p in url for p in ["cart", "basket"]):
            return PageIntent.CART
        if any(p in url for p in ["checkout", "payment"]):
            return PageIntent.CHECKOUT
        if any(p in url for p in ["confirm", "success", "thank"]):
            return PageIntent.CONFIRMATION
        if "search" in url or "results" in url:
            return PageIntent.SEARCH_RESULTS
        
        # Check page content
        text = await page.evaluate("() => document.body.innerText.toLowerCase()")
        
        if await detect_captcha(page):
            return PageIntent.CAPTCHA
        if any(p in text for p in ["sign in", "log in", "password"]) and "email" in text:
            return PageIntent.LOGIN
        if any(p in text for p in ["shopping cart", "your cart", "cart total"]):
            return PageIntent.CART
        if any(p in text for p in ["payment method", "credit card", "billing"]):
            return PageIntent.PAYMENT
        if any(p in text for p in ["order confirmed", "thank you", "confirmation number"]):
            return PageIntent.CONFIRMATION
        if "error" in title or "404" in text or "not found" in text:
            return PageIntent.ERROR
        
        return PageIntent.UNKNOWN
    except:
        return PageIntent.UNKNOWN


async def detect_captcha(page: Any) -> bool:
    """Detect if page has a *visible* CAPTCHA challenge.

    Previously this scanned full innerText / page HTML for "recaptcha".
    That false-positives on every Google property (YouTube, Search, Gmail,
    Drive) because reCAPTCHA libs are loaded site-wide as a string in
    bundled JS, even when no challenge is shown. The state-machine then
    paused for a human on every page transition.

    Real signal: a visible captcha *widget* in the DOM. We check for
    known iframes, the recaptcha anchor div, hCaptcha, Cloudflare Turnstile,
    or a visible "I'm not a robot" affordance. All elements must have
    non-zero size to count — invisible script tags don't.
    """
    try:
        return bool(await page.evaluate(
            """
            () => {
              const visible = el => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                if (r.width < 10 || r.height < 10) return false;
                const s = window.getComputedStyle(el);
                return s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
              };
              const selectors = [
                'iframe[src*="recaptcha/api2/anchor"]',
                'iframe[src*="recaptcha/enterprise/anchor"]',
                'iframe[src*="recaptcha/api2/bframe"]',
                'iframe[src*="hcaptcha.com/captcha"]',
                'iframe[src*="challenges.cloudflare.com"]',
                'div.g-recaptcha[data-sitekey]',
                'div.h-captcha[data-sitekey]',
                '#cf-challenge-running',
              ];
              for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (visible(el)) return true;
              }
              // Last-ditch: a visible checkbox or affordance literally
              // labeled "I'm not a robot".
              const labels = document.querySelectorAll('label, span, div');
              for (const el of labels) {
                const t = (el.textContent || '').trim().toLowerCase();
                if (t === "i'm not a robot" || t === 'im not a robot') {
                  if (visible(el)) return true;
                }
              }
              return false;
            }
            """
        ))
    except Exception:
        return False


async def detect_payment_page(page: Any) -> bool:
    """Detect if the current page is a real checkout/payment page.

    The previous version matched on any of {"payment method", "place order",
    "credit card"} appearing anywhere in the body text — which false-positived
    on every modern e-commerce *product* page because their footers carry
    payment-badge trust copy. That caused the state machine to short-circuit
    to PAYMENT_HANDOFF before the adapter ever clicked Buy Now.

    The fix: require the URL to look like a checkout / payment / cart route
    AS WELL AS the page text containing payment-form indicators. Product
    URLs (/products/..., /catalog/..., /search/...) never satisfy the URL
    gate, so they can't trip the detector regardless of footer content.
    """
    try:
        url = (page.url or "").lower()
        URL_GATES = (
            "/checkout", "/payment", "/cashier",
            "/buyer/order", "/buyer-order", "/order/",
            "/cart/checkout",
        )
        if not any(g in url for g in URL_GATES):
            return False

        indicators = (
            "payment method",
            "credit card",
            "card number",
            "cvv",
            "billing address",
            "place order",
            "complete purchase",
            "select payment",
            "choose payment",
        )
        text = await page.evaluate("() => document.body.innerText.toLowerCase()")
        return any(ind in text for ind in indicators)
    except Exception:
        return False


async def detect_login_required(page: Any) -> bool:
    """Detect if login is required."""
    try:
        url = page.url.lower()
        if any(p in url for p in ["login", "signin", "auth"]):
            return True
        
        text = await page.evaluate("() => document.body.innerText.toLowerCase()")
        indicators = ["sign in to continue", "login required", "please log in"]
        return any(ind in text for ind in indicators)
    except:
        return False


async def detect_checkout_flow(page: Any) -> bool:
    """Detect if in checkout flow."""
    try:
        url = page.url.lower()
        if any(p in url for p in ["checkout", "cart", "payment"]):
            return True
        
        text = await page.evaluate("() => document.body.innerText.toLowerCase()")
        indicators = ["checkout", "proceed to", "shipping", "billing"]
        return any(ind in text for ind in indicators)
    except:
        return False


async def extract_confirmation_number(page: Any) -> Optional[str]:
    """Extract order/confirmation number."""
    try:
        text = await page.evaluate("() => document.body.innerText")
        patterns = [
            r"order\s*#?\s*:?\s*([A-Z0-9-]+)",
            r"confirmation\s*#?\s*:?\s*([A-Z0-9-]+)",
            r"reference\s*#?\s*:?\s*([A-Z0-9-]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
        return None
    except:
        return None
