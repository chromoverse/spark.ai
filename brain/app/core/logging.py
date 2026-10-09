"""Structured JSON logs. trace/user/device ids come from contextvars set at the edges."""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime

trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)
device_id_var: ContextVar[str | None] = ContextVar("device_id", default=None)

# `extra` keys that must never reach a log line (RULES §9: log ids, not content).
_SECRET_KEYS = {
    "token",
    "access_token",
    "refresh_token",
    "code",
    "otp",
    "password",
    "secret",
    "authorization",
    "api_key",
    "code_verifier",
    "id_token",
}
_STD_ATTRS = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for name, var in (
            ("trace_id", trace_id_var),
            ("user_id", user_id_var),
            ("device_id", device_id_var),
        ):
            if (value := var.get()) is not None:
                out[name] = value
        for key, value in record.__dict__.items():
            if key not in _STD_ATTRS and not key.startswith("_"):
                out[key] = "[redacted]" if key.lower() in _SECRET_KEYS else value
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers[:] = []
        logging.getLogger(name).propagate = True
