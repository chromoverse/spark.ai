from enum import Enum
import logging

logger = logging.getLogger(__name__)

class FailureCategory(str, Enum):
    TRANSIENT = "transient"      # Retry with backoff (e.g. rate limit, timeout)
    RECOVERABLE = "recoverable"  # Re-planner can fix (e.g. tool/file not found, bad parameters)
    TERMINAL = "terminal"        # Immediate fail (e.g. auth expired, user denied, unsupported OS)

class ToolError(Exception):
    """Structured exception raised by tools to indicate specific failure categories."""
    def __init__(self, message: str, category: FailureCategory = FailureCategory.RECOVERABLE):
        super().__init__(message)
        self.category = category

def classify_failure(tool_name: str, exc: Exception) -> FailureCategory:
    """Classify a task execution exception into FailureCategory."""
    if isinstance(exc, ToolError):
        return exc.category

    error_message = str(exc)
    err = error_message.lower()

    # Transient Checks
    if any(x in err for x in ["timeout", "429", "rate limit", "connection refused", "econnrefused", "temporary error"]):
        return FailureCategory.TRANSIENT

    # Terminal Checks (No change of plans can fix this)
    if any(x in err for x in [
        "permission denied", "unauthorized", "auth failed",
        "unsupported target os", "invalid credentials", "hardware missing",
        "403", "access denied", "forbidden",
        "has not been used in project", "api has not been enabled",
        "is disabled", "accessnotconfigured",
        "access revoked", "re-auth required", "please reconnect",
        "no active gmail token", "no drive token",
    ]):
        return FailureCategory.TERMINAL

    # Default is Recoverable (LLM can replan or swap tools/parameters)
    # Note: "file not found", "directory not found", "tool not found" are RECOVERABLE
    return FailureCategory.RECOVERABLE
