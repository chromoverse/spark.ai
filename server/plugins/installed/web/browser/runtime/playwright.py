"""Playwright runtime with CDP attach."""
import asyncio
import logging
from typing import Callable, Any, Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from .base import BrowserRuntime
from ..errors import BrowserError, BrowserErrorType

logger = logging.getLogger(__name__)


class PlaywrightRuntime(BrowserRuntime):
    """CDP-attach Playwright runtime."""
    
    def __init__(self, cdp_url: str = "http://localhost:9222", dry_run: bool = False):
        super().__init__(dry_run)
        self.cdp_url = cdp_url
        self._playwright: Optional[Any] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._health_task: Optional[asyncio.Task] = None
        self._crash_callbacks: list[Callable] = []

    async def connect(self) -> None:
        """Connect to existing Chrome via CDP."""
        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.connect_over_cdp(self.cdp_url)
            contexts = self._browser.contexts
            if not contexts:
                raise BrowserError(
                    BrowserErrorType.BROWSER_DEAD,
                    "No browser contexts found after CDP connect"
                )
            self._context = contexts[0]
            self._connected = True
            self._health_task = asyncio.create_task(self._health_monitor())
            logger.info("PlaywrightRuntime connected to %s", self.cdp_url)
        except Exception as e:
            raise BrowserError(
                BrowserErrorType.BROWSER_DEAD,
                f"Failed to connect to browser: {e}"
            )

    async def new_page(self) -> Page:
        """Create new page in existing context."""
        if not self._context:
            raise BrowserError(BrowserErrorType.BROWSER_DEAD, "Not connected")
        page = await self._context.new_page()
        page.on("crash", lambda: self._on_page_crash(page))
        return page

    async def pages(self) -> list[Page]:
        """Return all pages in the context."""
        if not self._context:
            return []
        return self._context.pages

    async def disconnect(self) -> None:
        """Disconnect from browser."""
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._connected = False
        logger.info("PlaywrightRuntime disconnected")

    async def is_alive(self) -> bool:
        """Check browser health."""
        if not self._browser or not self._context:
            return False
        try:
            await asyncio.wait_for(
                asyncio.to_thread(lambda: self._context.pages),
                timeout=5.0
            )
            return True
        except:
            return False

    async def is_authenticated(self, *, hint_url: str) -> bool:
        """Check if authenticated (stub - checks for common auth cookies)."""
        if not self._context:
            return False
        try:
            cookies = await self._context.cookies(hint_url)
            auth_indicators = ["session", "auth", "token", "logged_in"]
            return any(
                any(ind in c.get("name", "").lower() for ind in auth_indicators)
                for c in cookies
            )
        except:
            return False

    async def on_tab_crashed(self, cb: Callable) -> None:
        """Register crash callback."""
        self._crash_callbacks.append(cb)

    def _on_page_crash(self, page: Page):
        """Handle page crash."""
        logger.error("Page crashed: %s", page.url)
        for cb in self._crash_callbacks:
            try:
                cb(page)
            except Exception as e:
                logger.exception("Crash callback failed: %s", e)

    async def _health_monitor(self):
        """Background health check every 30s."""
        while self._connected:
            try:
                await asyncio.sleep(30)
                if not await self.is_alive():
                    logger.error("Browser health check failed")
                    self._connected = False
                    break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Health monitor error: %s", e)
