"""Natural language time parsing — datetime and cron expressions."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import dateparser
from croniter import CroniterBadCronError, croniter

logger = logging.getLogger(__name__)

# Simple cron pattern mapping for common recurring phrases
_CRON_PATTERNS = {
    "every minute": "* * * * *",
    "every hour": "0 * * * *",
    "every morning": "0 9 * * *",
    "every evening": "0 18 * * *",
    "every night": "0 21 * * *",
    "every day": "0 9 * * *",
    "every monday": "0 9 * * 1",
    "every tuesday": "0 9 * * 2",
    "every wednesday": "0 9 * * 3",
    "every thursday": "0 9 * * 4",
    "every friday": "0 9 * * 5",
    "every saturday": "0 9 * * 6",
    "every sunday": "0 9 * * 0",
    "every weekday": "0 9 * * 1-5",
    "every weekend": "0 10 * * 6,0",
    "daily": "0 9 * * *",
    "hourly": "0 * * * *",
    "weekly": "0 9 * * 1",
}


def parse_datetime(text: str) -> Optional[datetime]:
    """Parse natural language time into a datetime. Returns None if unparseable."""
    if not text or not text.strip():
        return None

    # Try dateparser
    result = dateparser.parse(
        text,
        settings={
            "PREFER_DATES_FROM": "future",
            "RETURN_AS_TIMEZONE_AWARE": True,
        },
    )
    if result:
        # Ensure it's in the future
        now = datetime.now(timezone.utc)
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        if result <= now:
            result += timedelta(days=1)
        return result
    return None


def parse_cron(text: str) -> Optional[str]:
    """Parse natural language recurring pattern into a cron expression."""
    normalized = text.strip().lower()
    for pattern, cron in _CRON_PATTERNS.items():
        if pattern in normalized:
            return cron

    # If it looks like a raw cron expression, validate it via croniter
    parts = normalized.split()
    if len(parts) == 5:
        try:
            croniter(normalized)
            return normalized
        except (CroniterBadCronError, ValueError):
            return None
    return None


def cron_next_run(cron_expr: str, after: Optional[datetime] = None) -> Optional[datetime]:
    """
    Compute next run time from a cron expression using croniter.

    Returns a timezone-aware UTC datetime, or None if the expression is invalid.
    Handles arbitrary far-future cron schedules (e.g. yearly).
    """
    if not cron_expr:
        return None

    base = after or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)

    try:
        itr = croniter(cron_expr, base)
        nxt = itr.get_next(datetime)
        # croniter returns naive datetimes — re-attach UTC
        if nxt.tzinfo is None:
            nxt = nxt.replace(tzinfo=timezone.utc)
        return nxt
    except (CroniterBadCronError, ValueError, KeyError) as exc:
        logger.warning("Invalid cron expression %r: %s", cron_expr, exc)
        return None
