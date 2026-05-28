"""Typed error taxonomy for browser automation."""
from enum import Enum
from typing import Optional


class BrowserErrorType(str, Enum):
    ELEMENT_NOT_FOUND = "element_not_found"
    LOW_CONFIDENCE = "low_confidence"
    STALE_DOM = "stale_dom"
    DOM_NOT_STABLE = "dom_not_stable"
    NAVIGATION_FAILED = "navigation_failed"
    NETWORK_FAILED = "network_failed"
    TIMEOUT = "timeout"
    LOGIN_REQUIRED = "login_required"
    CAPTCHA = "captcha"
    PAYMENT_BLOCKED = "payment_blocked"
    BROWSER_DEAD = "browser_dead"
    TAB_CRASHED = "tab_crashed"
    BUDGET_EXCEEDED = "budget_exceeded"
    CIRCUIT_BREAKER = "circuit_breaker"
    GOAL_UNVERIFIED = "goal_unverified"
    FORBIDDEN_INTENT = "forbidden_intent"


class BrowserError(Exception):
    """Typed browser automation error."""
    def __init__(
        self,
        error_type: BrowserErrorType,
        detail: str,
        page_url: Optional[str] = None,
        evidence: Optional[dict] = None,
    ):
        self.type = error_type
        self.detail = detail
        self.page_url = page_url
        self.evidence = evidence or {}
        super().__init__(f"{error_type.value}: {detail}")
