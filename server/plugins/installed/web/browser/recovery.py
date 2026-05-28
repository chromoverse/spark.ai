"""Typed error recovery strategies."""
from dataclasses import dataclass
from typing import Optional, Any, Callable, Awaitable
from .errors import BrowserError, BrowserErrorType
from .semantic import click_by_text
import asyncio


@dataclass
class RecoveryResult:
    recovered: bool
    strategy: str
    detail: str


class RecoveryEngine:
    """Error-type-driven recovery."""
    
    def __init__(self, max_attempts: int = 3):
        self.max_attempts = max_attempts
        self._attempt_counts: dict[str, int] = {}
    
    async def attempt(self, page: Any, error: BrowserError, ctx: dict, runtime: Any) -> RecoveryResult:
        """Attempt recovery based on error type."""
        key = f"{error.type.value}_{ctx.get('state', 'unknown')}"
        self._attempt_counts[key] = self._attempt_counts.get(key, 0) + 1
        
        if self._attempt_counts[key] > self.max_attempts:
            return RecoveryResult(False, "max_attempts", f"Exceeded {self.max_attempts} attempts")
        
        strategies = self._STRATEGY_BY_TYPE.get(error.type, [])
        for strategy in strategies:
            result = await strategy(self, page, error, ctx, runtime)
            if result.recovered:
                self._attempt_counts[key] = 0  # Reset on success
                return result
        
        return RecoveryResult(False, "no_strategy", f"No recovery for {error.type.value}")
    
    async def _dismiss_cookie_banner(self, page: Any, error: BrowserError, ctx: dict, runtime: Any) -> RecoveryResult:
        """Try to dismiss cookie banner."""
        cookie_texts = ["Accept", "Accept all", "I agree", "OK", "Got it", "Close"]
        for text in cookie_texts:
            result = await click_by_text(page, text, runtime, kind="button")
            if result.ok:
                await asyncio.sleep(0.5)
                return RecoveryResult(True, "dismiss_cookie_banner", f"Dismissed via '{text}'")
        return RecoveryResult(False, "dismiss_cookie_banner", "No cookie banner found")
    
    async def _dismiss_popup(self, page: Any, error: BrowserError, ctx: dict, runtime: Any) -> RecoveryResult:
        """Try to dismiss modal/popup."""
        close_texts = ["Close", "×", "✕", "Dismiss", "No thanks"]
        for text in close_texts:
            result = await click_by_text(page, text, runtime)
            if result.ok:
                await asyncio.sleep(0.5)
                return RecoveryResult(True, "dismiss_popup", f"Dismissed via '{text}'")
        return RecoveryResult(False, "dismiss_popup", "No popup found")
    
    async def _retry_with_wait(self, page: Any, error: BrowserError, ctx: dict, runtime: Any) -> RecoveryResult:
        """Wait and retry."""
        await asyncio.sleep(1.0)
        return RecoveryResult(True, "retry_with_wait", "Waited 1s")
    
    async def _wait_longer_stable(self, page: Any, error: BrowserError, ctx: dict, runtime: Any) -> RecoveryResult:
        """Wait longer for DOM stability."""
        from .perception.dom import wait_dom_stable
        stable = await wait_dom_stable(page, settle_ms=1000, timeout_s=15.0)
        return RecoveryResult(stable, "wait_longer_stable", f"Stable: {stable}")
    
    async def _reload_once(self, page: Any, error: BrowserError, ctx: dict, runtime: Any) -> RecoveryResult:
        """Reload the page."""
        try:
            await page.reload(wait_until="domcontentloaded", timeout=20000)
            return RecoveryResult(True, "reload_once", "Page reloaded")
        except:
            return RecoveryResult(False, "reload_once", "Reload failed")
    
    async def _hand_to_human(self, page: Any, error: BrowserError, ctx: dict, runtime: Any) -> RecoveryResult:
        """Signal human intervention needed."""
        return RecoveryResult(False, "hand_to_human", f"Human needed: {error.type.value}")
    
    _STRATEGY_BY_TYPE: dict[BrowserErrorType, list[Callable]] = {
        BrowserErrorType.ELEMENT_NOT_FOUND: [
            _dismiss_cookie_banner,
            _dismiss_popup,
            _retry_with_wait
        ],
        BrowserErrorType.STALE_DOM: [_wait_longer_stable],
        BrowserErrorType.DOM_NOT_STABLE: [_wait_longer_stable],
        BrowserErrorType.NAVIGATION_FAILED: [_reload_once],
        BrowserErrorType.LOGIN_REQUIRED: [_hand_to_human],
        BrowserErrorType.CAPTCHA: [_hand_to_human],
    }
