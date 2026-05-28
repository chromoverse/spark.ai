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

    async def find_or_create_page(self, host_match: str | None = None) -> Page:
        """Reuse a tab whose URL contains ``host_match``; else create one.

        Why: keeps "play another song" reusing the YouTube tab instead of
        spawning a new one each time. The match is intentionally loose
        (substring on URL) so ``youtube.com/watch?...`` and
        ``youtube.com/results?...`` both count as "the YouTube tab".
        """
        if not self._context:
            raise BrowserError(BrowserErrorType.BROWSER_DEAD, "Not connected")

        if host_match:
            needle = host_match.lower()
            best: Optional[Page] = None
            for p in self._context.pages:
                url = (p.url or "").lower()
                if needle in url:
                    best = p
                    break
            if best is not None:
                return best

        # No match — prefer an existing about:blank/new-tab over spawning yet another.
        for p in self._context.pages:
            url = (p.url or "").lower()
            if url in ("", "about:blank", "chrome://newtab/"):
                return p

        return await self.new_page()

    async def bring_to_front(self, page: Page) -> None:
        """Raise the tab inside Chrome, then raise the Chrome window itself.

        page.bring_to_front handles the in-Chrome tab focus. On Windows we
        additionally pull the Chrome OS window to the foreground via the
        Win32 API, since CDP cannot do that for us. Failures are logged
        and swallowed — focus is best-effort, not a correctness requirement.
        """
        try:
            await page.bring_to_front()
        except Exception as e:
            logger.debug("page.bring_to_front failed: %s", e)

        # OS-level window raise (Windows only — no-op elsewhere).
        import sys
        if sys.platform != "win32":
            return
        try:
            await asyncio.to_thread(_raise_chrome_window_win32)
        except Exception as e:
            logger.debug("Windows foreground raise failed: %s", e)

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


def _raise_chrome_window_win32() -> None:
    """Find a Chrome top-level window and yank it to the foreground.

    Uses ctypes so we don't take a hard dep on pywin32. We look for the
    debug Chrome we launched (window class ``Chrome_WidgetWin_1`` and a
    visible window owned by chrome.exe). SetForegroundWindow has well-known
    rules — it can be denied when the calling process isn't the
    foreground; we work around that by sending a NULL ALT keypress first,
    which is the standard trick to unlock focus stealing.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi

    EnumWindowsProc = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
    )

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    SW_RESTORE = 9
    SW_SHOW = 5
    VK_MENU = 0x12  # ALT
    KEYEVENTF_KEYUP = 0x0002

    target_hwnd: list[int] = []

    def _proc_name_for(hwnd: int) -> str:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(260)
            size = wintypes.DWORD(260)
            if psapi.GetModuleBaseNameW(h, None, buf, size) > 0:
                return buf.value.lower()
            return ""
        finally:
            kernel32.CloseHandle(h)

    def _cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if cls.value != "Chrome_WidgetWin_1":
            return True
        if _proc_name_for(hwnd) != "chrome.exe":
            return True
        # Skip zero-area/tooltip windows.
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        if (rect.right - rect.left) < 100 or (rect.bottom - rect.top) < 100:
            return True
        target_hwnd.append(hwnd)
        return False  # stop enumerating

    user32.EnumWindows(EnumWindowsProc(_cb), 0)
    if not target_hwnd:
        return

    hwnd = target_hwnd[0]
    # If minimized, restore first.
    user32.ShowWindow(hwnd, SW_RESTORE)
    # Focus-stealing workaround: synthesize an ALT keypress so Windows
    # grants us SetForegroundWindow.
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    user32.ShowWindow(hwnd, SW_SHOW)
