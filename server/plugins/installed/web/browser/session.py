"""Process-wide persistent browser session.

Why this exists
───────────────
Before: every browser_action call did connect_over_cdp → run → disconnect.
That added ~1.5s of CDP handshake to every step and made follow-up commands
("pause", "next song", "skip ad") impossible because the runtime was gone
by the time the next utterance arrived.

After: one BrowserSession lives for the lifetime of the server process. It
lazy-connects on first use, holds the PlaywrightRuntime, hands out pages,
and silently reconnects if Chrome was killed and relaunched. Tools just
do ``await get_browser_session().get_page("youtube.com")`` and act on the
page; the session is responsible for keeping the connection alive.

Lifecycle
─────────
- Created on first ``get_browser_session()`` call.
- Cleaned up in the FastAPI lifespan shutdown hook (wired in app/main.py).
- Per-call ``get_page`` is safe to call concurrently — a single asyncio
  Lock serializes connect/reconnect, while page reads are fan-out.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional
from urllib.parse import urlparse

from playwright.async_api import Page

from .runtime.playwright import PlaywrightRuntime
from .errors import BrowserError, BrowserErrorType

logger = logging.getLogger(__name__)


class BrowserSession:
    """One long-lived CDP connection shared by every browser tool call."""

    def __init__(self, cdp_url: str = "http://localhost:9222") -> None:
        self._cdp_url = cdp_url
        self._runtime: Optional[PlaywrightRuntime] = None
        # Serializes connect / reconnect / disconnect. Read paths don't take it.
        self._lifecycle_lock = asyncio.Lock()
        self._shutdown = False

    # ─── Lifecycle ──────────────────────────────────────────────────────────

    async def _ensure_runtime(self) -> PlaywrightRuntime:
        """Return a connected runtime, (re)connecting if needed."""
        if self._shutdown:
            raise BrowserError(
                BrowserErrorType.BROWSER_DEAD,
                "BrowserSession has been shut down",
            )

        # Fast path: live runtime.
        rt = self._runtime
        if rt is not None and rt.connected and await rt.is_alive():
            return rt

        # Slow path: needs connect or reconnect — serialize.
        async with self._lifecycle_lock:
            # Re-check inside the lock (another task may have connected).
            rt = self._runtime
            if rt is not None and rt.connected and await rt.is_alive():
                return rt

            # Tear down dead runtime if present (best-effort).
            if rt is not None:
                logger.info("BrowserSession: stale runtime, disconnecting before reconnect")
                try:
                    await rt.disconnect()
                except Exception as e:
                    logger.debug("Disconnect of stale runtime failed (ignored): %s", e)
                self._runtime = None

            logger.info("BrowserSession: connecting to %s", self._cdp_url)
            rt = PlaywrightRuntime(cdp_url=self._cdp_url, dry_run=False)
            await rt.connect()
            self._runtime = rt
            return rt

    async def shutdown(self) -> None:
        """Disconnect cleanly. Called from the FastAPI shutdown hook."""
        async with self._lifecycle_lock:
            self._shutdown = True
            rt = self._runtime
            self._runtime = None
            if rt is None:
                return
            try:
                await rt.disconnect()
                logger.info("BrowserSession: shut down")
            except Exception as e:
                logger.warning("BrowserSession shutdown error (ignored): %s", e)

    # ─── Public API ─────────────────────────────────────────────────────────

    async def runtime(self) -> PlaywrightRuntime:
        """Get the live PlaywrightRuntime. Caller owns nothing — do not disconnect."""
        return await self._ensure_runtime()

    async def get_page(self, host_match: Optional[str] = None, *, focus: bool = True) -> Page:
        """Return a tab matching ``host_match`` (substring of URL), creating
        one if none exists. Brings Chrome to the foreground by default.

        ``host_match`` may be a full base URL (``https://www.youtube.com``)
        or a bare host (``youtube.com``); we normalize either way.
        """
        rt = await self._ensure_runtime()
        needle = _to_host(host_match) if host_match else None
        page = await rt.find_or_create_page(needle)
        if focus:
            await rt.bring_to_front(page)
        return page

    async def is_authenticated(self, hint_url: str) -> bool:
        """Forwarded to the runtime so callers don't need to reach inside."""
        rt = await self._ensure_runtime()
        return await rt.is_authenticated(hint_url=hint_url)


def _to_host(url_or_host: str) -> str:
    """``https://www.youtube.com/foo`` → ``youtube.com``. Pass-through
    if input already looks like a bare host."""
    s = url_or_host.strip().lower()
    if "://" in s:
        s = urlparse(s).netloc
    return s.removeprefix("www.")


# ─── Module-level singleton ────────────────────────────────────────────────

_SESSION: Optional[BrowserSession] = None


def get_browser_session() -> BrowserSession:
    """Return the process-wide BrowserSession (lazy-instantiated)."""
    global _SESSION
    if _SESSION is None:
        _SESSION = BrowserSession()
    return _SESSION


async def shutdown_browser_session() -> None:
    """Called from the FastAPI lifespan shutdown."""
    global _SESSION
    if _SESSION is not None:
        await _SESSION.shutdown()
        _SESSION = None


__all__ = ["BrowserSession", "get_browser_session", "shutdown_browser_session"]
