"""ShellSessionManager — per-user working directory and environment tracking."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional


@dataclass
class ShellSession:
    cwd: Path = field(default_factory=Path.home)
    env_overrides: Dict[str, str] = field(default_factory=dict)


class ShellSessionManager:
    def __init__(self):
        self._sessions: Dict[str, ShellSession] = {}

    def _ensure(self, user_id: str) -> ShellSession:
        if user_id not in self._sessions:
            self._sessions[user_id] = ShellSession()
        return self._sessions[user_id]

    def get_cwd(self, user_id: str, override: Optional[str] = None) -> Path:
        session = self._ensure(user_id)
        if override:
            p = Path(os.path.expanduser(override)).resolve()
            if p.is_dir():
                session.cwd = p
                return p
        if session.cwd.is_dir():
            return session.cwd
        return Path.home()

    def update_cwd(self, user_id: str, new_cwd: str) -> None:
        p = Path(new_cwd).resolve()
        if p.is_dir():
            self._ensure(user_id).cwd = p

    def build_env(self, user_id: str, overrides: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        env = dict(os.environ)
        session = self._ensure(user_id)
        env.update(session.env_overrides)
        if overrides:
            env.update(overrides)
        return env
