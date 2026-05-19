"""Artifact cleanup — age-based and size-based pruning."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from app.path.artifacts import get_artifact_store

logger = logging.getLogger(__name__)


def cleanup_old_artifacts(max_age_days: int = 30, max_total_mb: int = 500) -> int:
    """Remove artifacts older than max_age_days or when total exceeds max_total_mb.

    Returns number of artifacts removed.
    """
    store = get_artifact_store()
    records = store.list_artifacts(limit=9999)
    records.sort(key=lambda r: r.created_at)  # oldest first

    now = datetime.now(timezone.utc)
    total_bytes = sum(r.size_bytes for r in records)
    max_bytes = max_total_mb * 1024 * 1024
    removed = 0

    for record in records:
        try:
            created = datetime.fromisoformat(record.created_at)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age_days = (now - created).days
        except (ValueError, TypeError):
            age_days = 0

        too_old = age_days > max_age_days
        too_large = total_bytes > max_bytes

        if not (too_old or too_large):
            continue

        # Delete the actual file
        artifact_path = store.resolve_artifact_path(record)
        if artifact_path.exists():
            artifact_path.unlink()

        # Delete the record sidecar
        record_path = store._record_path(record.artifact_id)
        if record_path.exists():
            record_path.unlink()

        total_bytes -= record.size_bytes
        removed += 1
        logger.debug("Removed artifact: %s (age=%dd)", record.artifact_id, age_days)

    if removed:
        logger.info("Artifact cleanup: removed %d artifacts", removed)
    return removed
