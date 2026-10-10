"""Installed-app index (Start Menu shortcuts) and app_open. The reflex arc only accepts
"open X" when X is in this index (REDESIGN §27)."""

from __future__ import annotations

import difflib
import os
import sys
from pathlib import Path
from typing import Any

VENDORS = ("google ", "microsoft ", "mozilla ", "adobe ")
ALIASES = {
    "vs code": "visual studio code",
    "vscode": "visual studio code",
    "code": "visual studio code",
    "explorer": "file explorer",
    "files": "file explorer",
    "calc": "calculator",
}
# Generic names → the first installed app that fits ("open my browser")
GENERIC = {
    "browser": ("google chrome", "microsoft edge", "firefox", "brave", "opera"),
    "web browser": ("google chrome", "microsoft edge", "firefox", "brave", "opera"),
    "music": ("spotify", "apple music", "media player"),
}


class NotInstalled(Exception):
    pass


def _start_menu_dirs() -> list[Path]:
    dirs = []
    for env in ("PROGRAMDATA", "APPDATA"):
        base = os.environ.get(env)
        if base:
            dirs.append(Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    return dirs


class AppIndex:
    """spoken name → (display name, launch target)."""

    def __init__(self, entries: dict[str, tuple[str, str]] | None = None) -> None:
        self.entries: dict[str, tuple[str, str]] = entries or {}

    @classmethod
    def scan(cls, dirs: list[Path] | None = None) -> AppIndex:
        entries: dict[str, tuple[str, str]] = {}
        for d in dirs if dirs is not None else _start_menu_dirs():
            for lnk in d.rglob("*.lnk") if d.is_dir() else []:
                name = lnk.stem
                low = name.lower()
                if "uninstall" in low or "readme" in low or "help" in low:
                    continue
                entries.setdefault(low, (name, str(lnk)))
                for vendor in VENDORS:
                    if low.startswith(vendor):
                        entries.setdefault(low[len(vendor) :], (name, str(lnk)))
        for alias, target in ALIASES.items():
            if target in entries:
                entries.setdefault(alias, entries[target])
        for alias, targets in GENERIC.items():
            if found := next((t for t in targets if t in entries), None):
                entries.setdefault(alias, entries[found])
        return cls(entries)

    def spoken(self) -> dict[str, str]:
        """For the reflex arc: spoken name → display name."""
        return {k: v[0] for k, v in self.entries.items()}

    def resolve(self, app: str) -> tuple[str, str] | None:
        low = app.lower().strip()
        if low in self.entries:
            return self.entries[low]
        for display, target in self.entries.values():
            if display.lower() == low:
                return display, target
        return None

    def close_matches(self, app: str) -> list[str]:
        names = sorted({v[0] for v in self.entries.values()})
        return difflib.get_close_matches(app, names, n=3, cutoff=0.5)


INDEX = AppIndex()


def app_open(inp: dict[str, Any]) -> dict[str, Any]:
    app = str(inp["app"])
    hit = INDEX.resolve(app)
    if hit is None:
        close = INDEX.close_matches(app)
        hint = f" Close matches: {', '.join(close)}." if close else ""
        raise NotInstalled(f"No app named {app!r} is installed here.{hint}")
    display, target = hit
    if sys.platform == "win32":
        os.startfile(target)  # noqa: S606 (a Start Menu shortcut from the index)
    return {"opened": display}
