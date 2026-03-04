from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler

from app.kernel.observability.log_index import get_kernel_log_index


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
            "user_id": getattr(record, "user_id", None),
            "request_id": getattr(record, "request_id", None),
            "session_id": getattr(record, "session_id", None),
            "startup_id": get_kernel_log_index().startup_id,
        }
        return json.dumps(payload, ensure_ascii=True)


def configure_structured_logging() -> None:
    root = logging.getLogger()
    if getattr(root, "_spark_logging_configured", False):
        return

    root.setLevel(logging.INFO)
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    log_file = get_kernel_log_index().log_file
    file_handler = RotatingFileHandler(
        filename=str(log_file),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(JsonLineFormatter())

    root.addHandler(console)
    root.addHandler(file_handler)
    root._spark_logging_configured = True  # type: ignore[attr-defined]


