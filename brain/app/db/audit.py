from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog


def audit(
    db: AsyncSession,
    user_id: uuid.UUID | None,
    action: str,
    *,
    actor: str = "user",
    target: str | None = None,
    **meta: Any,
) -> None:
    """Adds an audit row to the caller's transaction. Ids only, never secrets or content."""
    db.add(AuditLog(user_id=user_id, actor=actor, action=action, target=target, meta=meta))
