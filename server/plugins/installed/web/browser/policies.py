"""Budgets, retry policies, and circuit breaker."""
from dataclasses import dataclass, field
from .errors import BrowserErrorType

# Hard limits
MAX_FLOW_DURATION_S = 300
MAX_ACTIONS_PER_FLOW = 50
MAX_PAGE_LOAD_WAIT_S = 20
MAX_RECOVERY_PER_STATE = 3
CIRCUIT_LOW_CONF_STREAK = 5
CONFIDENCE_GATE = 0.7


@dataclass
class RetryPolicy:
    retries: int = 0
    backoff: float = 1.0
    retry_on: set[BrowserErrorType] = field(default_factory=set)


DEFAULT_RETRY: dict[BrowserErrorType, RetryPolicy] = {
    BrowserErrorType.STALE_DOM: RetryPolicy(2, 0.5, {BrowserErrorType.STALE_DOM}),
    BrowserErrorType.DOM_NOT_STABLE: RetryPolicy(2, 0.8, {BrowserErrorType.DOM_NOT_STABLE}),
    BrowserErrorType.NAVIGATION_FAILED: RetryPolicy(1, 1.5, {BrowserErrorType.NAVIGATION_FAILED}),
    BrowserErrorType.NETWORK_FAILED: RetryPolicy(2, 1.5, {BrowserErrorType.NETWORK_FAILED}),
    BrowserErrorType.LOW_CONFIDENCE: RetryPolicy(1, 0.5, {BrowserErrorType.LOW_CONFIDENCE}),
}


class CircuitBreaker:
    """Trips on N consecutive low-confidence actions; resets on high-conf."""
    def __init__(self, threshold: int = CIRCUIT_LOW_CONF_STREAK):
        self.threshold = threshold
        self.streak = 0
        self.tripped = False

    def record(self, conf: float) -> bool:
        """Record confidence score. Returns True if tripped."""
        if conf >= CONFIDENCE_GATE:
            self.streak = 0
            self.tripped = False
        else:
            self.streak += 1
            if self.streak >= self.threshold:
                self.tripped = True
        return self.tripped

    def reset(self):
        self.streak = 0
        self.tripped = False
