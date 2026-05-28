"""Auto-launch Chrome with the remote debugging port we attach to.

Why this exists
───────────────
``BrowserSession`` only *attaches* over CDP. If Chrome isn't already
running with ``--remote-debugging-port=9222``, every browser_action dies
with ``BROWSER_DEAD: Failed to connect to browser``. Telling the user to
keep a separate ``start_chrome_debug.py`` window open is fragile; the
session itself should bring up Chrome when nobody else has.

Behavior
────────
``ensure_chrome_running`` is idempotent:
  • Port 9222 already open → no-op.
  • Otherwise locate ``chrome.exe`` (Windows) / ``google-chrome`` (Linux) /
    ``Google Chrome`` (macOS), spawn it with our persistent
    ``--user-data-dir`` so the user's Daraz / Google / etc sign-ins stick
    around, and poll the port for ~``wait_s`` seconds.

The profile lives at ``~/.sparkai_data/chrome_profile`` — separate from
the user's everyday Chrome so we don't fight over the same lockfile.
Sign in to Daraz inside *this* Chrome once and it persists.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_PORT = 9222
# Same profile dir the testing scripts (test_browser_*_e2e.py) use, so a
# one-time Daraz / Google sign-in inside *either* launch path carries
# over to the other. Don't change this casually — moving it invalidates
# every saved session the user already has.
_DEFAULT_PROFILE_DIR = Path.home() / ".chrome-debug-profile"


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        return sock.connect_ex((host, port)) == 0
    finally:
        sock.close()


def _find_chrome_executable() -> Optional[str]:
    """Locate Chrome / Chromium / Edge on the host. Returns None if none found.

    Order: known install paths → PATH lookup → Edge (Chromium) as last
    resort so users without Chrome still get a working browser session.
    """
    if sys.platform == "win32":
        candidates: List[str] = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
            # Chromium-based Edge — same CDP protocol, works as a drop-in.
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        path_names = ("chrome", "chrome.exe", "msedge", "msedge.exe")
    elif sys.platform == "darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ]
        path_names = ("google-chrome", "chromium", "chrome")
    else:
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/snap/bin/chromium",
            "/usr/bin/microsoft-edge",
        ]
        path_names = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")
    for p in candidates:
        if p and os.path.exists(p):
            return p
    # Fall back to PATH lookup — covers nonstandard installs.
    for name in path_names:
        found = shutil.which(name)
        if found:
            return found
    return None


def _spawn_chrome(chrome_path: str, port: int, profile_dir: Path) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        chrome_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--restore-last-session",
        "about:blank",
    ]
    creationflags = 0
    if sys.platform == "win32":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP — don't tie Chrome's
        # lifetime to ours, don't carry our console handle.
        creationflags = 0x00000008 | 0x00000200
    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creationflags,
    )


class LaunchResult:
    """Outcome of an auto-launch attempt. ``ok`` for success; ``reason``
    is the human-readable explanation we surface to the caller (and via
    BrowserError to the user) when it didn't work."""

    __slots__ = ("ok", "reason")

    def __init__(self, ok: bool, reason: str = "") -> None:
        self.ok = ok
        self.reason = reason


async def ensure_chrome_running(
    *,
    port: int = _DEFAULT_PORT,
    profile_dir: Path = _DEFAULT_PROFILE_DIR,
    wait_s: float = 10.0,
) -> LaunchResult:
    """Make sure Chrome is reachable on ``port``.

    Idempotent. Safe to call before every connect attempt — when the port
    is already open we return in <1ms.
    """
    if _port_open("127.0.0.1", port):
        return LaunchResult(True, f"already listening on :{port}")

    chrome_path = _find_chrome_executable()
    if chrome_path is None:
        msg = (
            "Chrome / Chromium / Edge not found on this host. Install one, "
            "or launch Chrome manually with: "
            f'chrome.exe --remote-debugging-port={port} '
            f'--user-data-dir="{profile_dir}"'
        )
        logger.warning("ensure_chrome_running: %s", msg)
        return LaunchResult(False, msg)

    logger.info("ensure_chrome_running: launching %s on port %d", chrome_path, port)
    try:
        await asyncio.to_thread(_spawn_chrome, chrome_path, port, profile_dir)
    except Exception as exc:
        msg = f"failed to spawn {chrome_path}: {exc}"
        logger.warning("ensure_chrome_running: %s", msg)
        return LaunchResult(False, msg)

    # Poll until the debug port answers or we give up.
    deadline = asyncio.get_event_loop().time() + wait_s
    while asyncio.get_event_loop().time() < deadline:
        if _port_open("127.0.0.1", port):
            logger.info("ensure_chrome_running: Chrome is up on port %d", port)
            return LaunchResult(True, f"launched and listening on :{port}")
        await asyncio.sleep(0.25)

    msg = (
        f"Chrome process spawned but did not open port {port} within {wait_s:.1f}s. "
        "Most common cause: a normal Chrome was already running and the new "
        "process attached to it instead of starting fresh. Close all Chrome "
        "windows and try again."
    )
    logger.warning("ensure_chrome_running: %s", msg)
    return LaunchResult(False, msg)


__all__ = ["ensure_chrome_running", "LaunchResult"]
