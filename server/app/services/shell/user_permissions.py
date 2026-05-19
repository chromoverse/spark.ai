"""Persistent user permission store — remembers granted shell permissions."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from app.path.manager import PathManager

logger = logging.getLogger(__name__)


class UserPermissionStore:
    """Stores permanently granted command permissions in user_permissions.json.

    Supports per-command grants and a blanket "full_access" flag that bypasses
    all future approval prompts for a given user.
    """

    def __init__(self):
        self._path = PathManager().layout.db_dir / "user_permissions.json"
        self._data: dict = self._load()

    def _load(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def _ensure_user(self, user_id: str) -> dict:
        return self._data.setdefault(user_id, {"full_access": False, "allowed_commands": []})

    def has_full_access(self, user_id: str) -> bool:
        return bool(self._data.get(user_id, {}).get("full_access", False))

    def is_permitted(self, user_id: str, command_prefix: str) -> bool:
        """Check if user has full access or a per-command grant."""
        if self.has_full_access(user_id):
            return True
        perms = self._data.get(user_id, {}).get("allowed_commands", [])
        token = command_prefix.strip().split()[0].lower() if command_prefix.strip() else ""
        return token in perms

    def grant(self, user_id: str, command_prefix: str) -> None:
        """Permanently grant permission for a single command prefix."""
        token = command_prefix.strip().split()[0].lower() if command_prefix.strip() else ""
        if not token:
            return
        user_data = self._ensure_user(user_id)
        if token not in user_data["allowed_commands"]:
            user_data["allowed_commands"].append(token)
            self._save()
            logger.info("Permission granted for user=%s command=%s", user_id, token)

    def grant_full_access(self, user_id: str) -> None:
        """Grant blanket permission — skip all future approval prompts."""
        user_data = self._ensure_user(user_id)
        user_data["full_access"] = True
        self._save()
        logger.info("Full shell access granted for user=%s", user_id)

    def revoke_full_access(self, user_id: str) -> None:
        """Revoke blanket permission — revert to per-command approval."""
        if user_id in self._data:
            self._data[user_id]["full_access"] = False
            self._save()
            logger.info("Full shell access revoked for user=%s", user_id)


_instance: Optional[UserPermissionStore] = None


def get_user_permission_store() -> UserPermissionStore:
    global _instance
    if _instance is None:
        _instance = UserPermissionStore()
    return _instance
