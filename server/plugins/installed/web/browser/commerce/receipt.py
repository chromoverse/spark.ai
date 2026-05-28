"""Receipt capture + disk persistence.

What lives here
───────────────
Anything that turns a "we landed on a purchase-confirmation page" event
into a durable artifact — a structured ``Receipt`` dict, a screenshot, a
HTML dump, all in one folder per purchase. This module is purely
mechanical: it does NOT know what to scrape (that's the adapter's job),
it just takes the dict the adapter produced and persists it.

Why a dict and not a class
──────────────────────────
Receipts vary wildly across sites — Daraz returns line items + shipping
ETA; Booking returns check-in/out dates; Amazon returns serial numbers.
A typed ``dataclass`` would either be useless-and-loose or balloon to
fit every site. We standardize the *envelope* (order_id, total, items,
captured_at, source_url) and let the adapter pack whatever else makes
sense under ``raw``.

Disk layout
───────────
    ~/.sparkai_data/receipts/<YYYYMMDD-HHMMSS>-<order_id>/
        receipt.json     ← the dict, serialized
        page.png         ← full-page screenshot
        page.html        ← rendered HTML at capture time (for re-parse later)

If anything fails (screenshot timeout, write error), we save what we
can and surface the failure in the return dict — partial receipts are
better than none.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

RECEIPTS_DIR = Path.home() / ".sparkai_data" / "receipts"


# ── Receipt envelope ────────────────────────────────────────────────────────

# Standardized keys. Adapters MAY include more under ``raw``, but they
# SHOULD populate these whenever the page exposes them. The watcher
# treats a missing order_id as a soft warning, not a failure — some
# sites bury it three clicks deep in "My Orders".
REQUIRED_KEYS = ("source", "captured_at", "source_url")
RECOMMENDED_KEYS = ("order_id", "total", "currency", "items")


@dataclass
class SavedReceipt:
    """Where a captured receipt lives on disk + minimal metadata."""
    dir: Path
    receipt_path: Path
    screenshot_path: Optional[Path]
    html_path: Optional[Path]
    data: dict


# ── Capture ────────────────────────────────────────────────────────────────

async def capture_page_artifacts(page: Any, dest_dir: Path) -> dict[str, Optional[Path]]:
    """Snapshot the page (screenshot + HTML) into ``dest_dir``.

    Returns a dict with ``screenshot`` and ``html`` keys mapping to the
    paths actually written (None if a particular capture failed).
    Failures are logged, not raised — we'd rather save a partial record
    than lose the whole purchase.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, Optional[Path]] = {"screenshot": None, "html": None}

    screenshot_path = dest_dir / "page.png"
    try:
        await page.screenshot(path=str(screenshot_path), full_page=True, timeout=15_000)
        out["screenshot"] = screenshot_path
    except Exception as e:
        logger.warning("receipt: screenshot failed: %s", e)

    html_path = dest_dir / "page.html"
    try:
        html = await page.content()
        html_path.write_text(html, encoding="utf-8")
        out["html"] = html_path
    except Exception as e:
        logger.warning("receipt: HTML capture failed: %s", e)

    return out


def save_receipt(
    receipt: dict,
    *,
    base_dir: Path = RECEIPTS_DIR,
) -> SavedReceipt:
    """Write ``receipt`` to disk under ``base_dir/<ts>-<order_id>/``.

    Doesn't write a screenshot or HTML — call ``capture_page_artifacts``
    against the same directory before/after this. We keep them separate
    so a re-save (e.g. status update) doesn't reshoot the page.
    """
    _validate_envelope(receipt)
    ts = time.strftime("%Y%m%d-%H%M%S", time.localtime(receipt.get("captured_at", time.time())))
    order_id = _safe_id(receipt.get("order_id"))
    dir_name = f"{ts}-{order_id}" if order_id else ts
    dest = base_dir / dir_name
    dest.mkdir(parents=True, exist_ok=True)

    receipt_path = dest / "receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("receipt: saved %s", receipt_path)
    return SavedReceipt(
        dir=dest,
        receipt_path=receipt_path,
        screenshot_path=(dest / "page.png") if (dest / "page.png").exists() else None,
        html_path=(dest / "page.html") if (dest / "page.html").exists() else None,
        data=receipt,
    )


# ── Helpers ────────────────────────────────────────────────────────────────

def _validate_envelope(receipt: dict) -> None:
    """Mutate ``receipt`` so REQUIRED_KEYS are present; warn on missing recommended."""
    if not isinstance(receipt, dict):
        raise TypeError(f"receipt must be dict, got {type(receipt).__name__}")
    receipt.setdefault("captured_at", time.time())
    receipt.setdefault("source", "unknown")
    receipt.setdefault("source_url", "")
    missing = [k for k in RECOMMENDED_KEYS if k not in receipt]
    if missing:
        logger.info("receipt: missing recommended keys %s — saving anyway", missing)


_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_id(s: Any) -> Optional[str]:
    """Filesystem-safe order id. Returns None for falsy / unusable inputs."""
    if not s:
        return None
    out = _SAFE_ID_RE.sub("_", str(s)).strip("._-")
    return out or None


__all__ = [
    "RECEIPTS_DIR",
    "SavedReceipt",
    "capture_page_artifacts",
    "save_receipt",
]
