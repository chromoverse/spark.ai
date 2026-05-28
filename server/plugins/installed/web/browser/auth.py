"""Generic first-run authentication helper.

Why this exists
───────────────
Spotify, Amazon, Booking.com — anything useful — requires login. We DO
NOT want to type passwords for the user, and we DO NOT want to ferry
credentials through our process. The clean pattern, validated by every
production browser-agent product, is:

  1. Check declaratively whether the user is signed in (DOM selector +
     optional cookie hint).
  2. If yes: continue.
  3. If no: navigate the live tab to the site's login URL, raise the
     Chrome window so the user sees it, then **block** waiting for the
     signed-in marker to appear in the DOM. The user types their
     password (and 2FA, captcha, whatever); we resume as soon as the
     marker shows up.

The persistent profile in ``~/.chrome-debug-profile`` keeps the resulting
session cookies, so step 3 only happens once per site for the lifetime of
that profile. Across server restarts the cookies survive — this is the
*entire* point of using a persistent user-data-dir.

Each site declares one ``AuthSpec`` and adapters call ``ensure_signed_in``
from their ``do_init``. No more boilerplate per adapter.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from .events import BrowserEvent, BrowserEventType, get_event_bus
from .human_loop import pause_for_human

logger = logging.getLogger(__name__)


@dataclass
class AuthSpec:
    """Declarative auth check for one site."""
    name: str                                     # 'spotify', 'amazon', ...
    login_url: str                                # send user here to sign in
    home_url: str                                 # app home (where we check DOM markers)
    signed_in_selector: Optional[str] = None      # DOM selector present iff signed in
    signed_out_selectors: tuple = ()              # any of these visible ⇒ signed out
    cookie_indicators: tuple = ()                 # substrings expected in cookie names
    # Some sites set the signed-in selector lazily — give the page a beat
    # to hydrate before we judge. Tunable per site if needed.
    settle_ms: int = 800


async def is_signed_in(page: Any, spec: AuthSpec, *, navigate: bool = True) -> bool:
    """Return True if the page looks signed in for ``spec``.

    ``navigate`` controls whether we may load ``spec.home_url`` to check.
    Use ``navigate=True`` for the upfront check (we *want* to land on
    home if we're not already there) and ``navigate=False`` while polling
    inside a sign-in loop — otherwise we'd re-navigate every second and
    kick the user out of the login form on ``accounts.spotify.com`` /
    similar OAuth pages.

    Strategy (cheapest first):
      1. Cookies — substring match on session-cookie names. Works on any
         tab; doesn't need us to be on the home page. Most reliable
         signal for Spotify/Amazon/Google-style sessions.
      2. If we're already on the site (or ``navigate`` is True), check
         the DOM: ``signed_in_selector`` present ⇒ True;
         ``signed_out_selectors`` present ⇒ False.
      3. Otherwise return False.
    """
    # Step 1: cookies — cheap, navigation-free, very reliable for major sites.
    if spec.cookie_indicators:
        try:
            ctx = page.context
            cookies = await ctx.cookies(spec.home_url)
            names = {(c.get("name") or "").lower() for c in cookies}
            for hint in spec.cookie_indicators:
                if any(hint.lower() in n for n in names):
                    return True
        except Exception as e:
            logger.debug("auth.is_signed_in cookie check failed: %s", e)

    # Step 2: DOM check. We need to be on the site for this; if we're
    # somewhere else AND we're not allowed to navigate (poll mode),
    # skip — cookies are our only signal in that case.
    target_host = _host(spec.home_url)
    on_site = target_host in (page.url or "").lower()
    if not on_site:
        if not navigate:
            return False
        try:
            await page.goto(spec.home_url, wait_until="domcontentloaded", timeout=15_000)
        except Exception as e:
            logger.debug("auth.is_signed_in goto failed: %s", e)
            return False

    if spec.settle_ms > 0:
        await page.wait_for_timeout(spec.settle_ms)

    # Positive marker wins.
    if spec.signed_in_selector:
        try:
            if await page.locator(spec.signed_in_selector).count() > 0:
                return True
        except Exception as e:
            logger.debug("auth.is_signed_in positive selector check failed: %s", e)

    # Negative marker means definitely not signed in.
    for sel in spec.signed_out_selectors:
        try:
            if await page.locator(sel).count() > 0:
                return False
        except Exception as e:
            logger.debug("auth.is_signed_in negative selector %r failed: %s", sel, e)

    # No definitive DOM signal and no cookie match — conservative no.
    return False


async def ensure_signed_in(
    page: Any,
    spec: AuthSpec,
    runtime: Any = None,
    *,
    timeout_s: float = 120.0,
    reminder_every_s: float = 5.0,
) -> bool:
    """Make sure the user is signed in for ``spec``; block until they are.

    If already signed in → returns True immediately.
    If not → navigates to ``spec.login_url``, brings Chrome to front, and
    polls until the signed-in marker appears, re-emitting AWAITING_USER
    every ``reminder_every_s`` seconds (default 5s) up to ``timeout_s``
    (default 120s). After the timeout we give up so the calling tool can
    fail cleanly instead of pinning the assistant indefinitely.

    Returns True on success, False on timeout. Adapters should treat
    False as a hard abort condition (we can't proceed without auth).
    """
    if await is_signed_in(page, spec):
        logger.info("auth: already signed in to %s", spec.name)
        return True

    logger.info("auth: %s — not signed in, asking user to authenticate", spec.name)

    # Send them to the login page in the SAME tab (no new tab clutter).
    try:
        await page.goto(spec.login_url, wait_until="domcontentloaded", timeout=15_000)
    except Exception as e:
        logger.warning("auth: failed to navigate to login URL %r: %s", spec.login_url, e)
        # Continue anyway — they may already be on the login page.

    # Pull Chrome to the foreground so they see what's happening.
    if runtime is not None:
        try:
            await runtime.bring_to_front(page)
        except Exception as e:
            logger.debug("auth: bring_to_front failed (ignored): %s", e)

    # Predicate: signed-in marker appears. navigate=False is critical —
    # while the user is typing their password on accounts.spotify.com,
    # we MUST NOT navigate back to open.spotify.com on every poll.
    async def _check(p: Any) -> bool:
        return await is_signed_in(p, spec, navigate=False)

    # pause_for_human handles the initial AWAITING_USER emit + periodic
    # reminders + timeout. We just pass the site-specific context through
    # so the UI can render a helpful prompt.
    ok = await pause_for_human(
        page,
        reason="sign_in_required",
        predicate=_check,
        timeout_s=timeout_s,
        reminder_every_s=reminder_every_s,
        message=f"Please sign in to {spec.name.capitalize()} in the browser window.",
        extra={"site": spec.name, "login_url": spec.login_url},
    )
    if ok:
        logger.info("auth: %s — user signed in", spec.name)
    else:
        logger.warning("auth: %s — sign-in not completed within %.0fs", spec.name, timeout_s)
    return ok


def _host(url: str) -> str:
    """Bare host for substring matching against page.url."""
    from urllib.parse import urlparse
    return urlparse(url).netloc.lower().removeprefix("www.")


__all__ = ["AuthSpec", "is_signed_in", "ensure_signed_in"]
