"""Desktop notification helper for browser-agent flows.

Why this exists
───────────────
Event-bus messages only reach subscribers — terminal output, Electron UI,
whatever's listening. But when the agent hands off to the user mid-flow
("fill your shipping address", "complete payment"), the user is in the
*browser*, not looking at the terminal or the Spark UI. We need a
real OS-level notification that pops over whatever window has focus.

Implementation
──────────────
Uses ``windows-toasts`` (already in server/requirements.txt) for native
Windows 10/11 toast notifications. If Windows refuses native toasts for
this Python process, falls back to a visible auto-dismissing Windows
popup so checkout handoffs are still seen while Chrome has focus.

API
───
    notify("Daraz", "Fill your address", url=None, sound=True)
    notify_stage_change(adapter_name, stage, guidance)
    is_available() -> bool

Module-level singleton WindowsToaster — instantiating one per call is
allowed by the lib but wasteful. We create it lazily on first ``notify``.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
from typing import Optional

logger = logging.getLogger(__name__)


# ── Backend probe ──────────────────────────────────────────────────────────

_BACKEND: Optional[str] = None
_WINDOWS_TOASTS_FAILED = False
_TOASTER = None
_LOCK = threading.Lock()


def _notifications_enabled() -> bool:
    raw = os.getenv("SPARK_BROWSER_NOTIFICATIONS", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _init_backend() -> Optional[str]:
    """Pick the best available notification backend on this platform.

    Returns the backend name (``"windows_toasts"`` for now) or None if
    none works. Cached after first call.
    """
    global _BACKEND, _TOASTER
    if _BACKEND is not None:
        return _BACKEND or None

    with _LOCK:
        if _BACKEND is not None:
            return _BACKEND or None

        if sys.platform != "win32":
            logger.debug("notify: non-Windows platform, no toast backend")
            _BACKEND = ""
            return None

        try:
            from windows_toasts import WindowsToaster
            _TOASTER = WindowsToaster("Spark AI")
            _BACKEND = "windows_toasts"
            logger.info("notify: using windows-toasts backend")
            return _BACKEND
        except Exception as e:
            logger.warning(
                "notify: windows-toasts not available (%s). "
                "Install it with: pip install windows-toasts", e
            )
            _BACKEND = ""
            return None


def is_available() -> bool:
    """True if we can actually pop a desktop notification."""
    if not _notifications_enabled():
        return False
    if bool(_init_backend()):
        return True
    return sys.platform == "win32" and bool(_find_powershell())


# ── Public API ─────────────────────────────────────────────────────────────

def notify(
    title: str,
    message: str,
    *,
    url: Optional[str] = None,
    sound: bool = True,
    tag: Optional[str] = None,
    group: Optional[str] = None,
    allow_popup_fallback: bool = True,
) -> bool:
    """Fire one desktop toast. Returns True if shown, False if backend missing.

    Failures are swallowed — a notification system that crashes a buy flow
    would be worse than no notification at all. We always log the attempt.
    """
    if not _notifications_enabled():
        logger.info("notify disabled: %s — %s", title, message)
        return False

    if _try_windows_toast(title, message, sound=sound, tag=tag, group=group):
        return True

    if allow_popup_fallback and _show_windows_popup(title, message, sound=sound):
        return True

    logger.info("notify (no backend): %s — %s", title, message)
    return False


def _try_windows_toast(
    title: str,
    message: str,
    *,
    sound: bool,
    tag: Optional[str],
    group: Optional[str],
) -> bool:
    """Use windows-toasts when Windows allows this process to publish toasts."""
    global _WINDOWS_TOASTS_FAILED
    if _WINDOWS_TOASTS_FAILED:
        return False

    backend = _init_backend()
    if not backend:
        return False

    try:
        from windows_toasts import Toast, ToastDuration
        toast = Toast()
        toast.text_fields = [title, message]
        toast.duration = ToastDuration.Long  # ~25s, vs Short ~7s
        if tag:
            toast.tag = tag
        if group:
            toast.group = group
        if not sound:
            # windows-toasts >= 1.0 exposes audio control:
            try:
                from windows_toasts import AudioSource, ToastAudio
                toast.audio = ToastAudio(silent=True)
            except Exception:
                pass
        # Future: pass ``url`` as a click action via toast.on_activated.
        _TOASTER.show_toast(toast)  # type: ignore[union-attr]
        return True
    except Exception as e:
        logger.warning("notify: failed to show toast (%s): %s", title, e)
        _WINDOWS_TOASTS_FAILED = True
        return False


def _find_powershell() -> Optional[str]:
    return (
        shutil.which("powershell.exe")
        or shutil.which("powershell")
        or shutil.which("pwsh.exe")
        or shutil.which("pwsh")
    )


def _show_windows_popup(title: str, message: str, *, sound: bool) -> bool:
    """Last-resort visible alert for Windows toast permission failures.

    Some local Python processes can import ``windows-toasts`` but Windows
    refuses ``ToastNotifier.show`` with ``Access is denied`` unless the app
    identity is registered. ``WScript.Shell.Popup`` is less pretty than a
    native toast, but it is visible over Chrome and auto-dismisses, which is
    exactly what a checkout handoff needs.
    """
    if sys.platform != "win32":
        return False

    powershell = _find_powershell()
    if not powershell:
        return False

    payload = json.dumps(
        {
            "title": str(title)[:120],
            "message": str(message)[:700],
            "flags": 64 if sound else 0,  # 64 = information icon + system cue
        },
        ensure_ascii=False,
    )
    payload_b64 = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    script = f"""
$payload = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{payload_b64}')) | ConvertFrom-Json
$ws = New-Object -ComObject WScript.Shell
$null = $ws.Popup([string]$payload.message, 12, [string]$payload.title, [int]$payload.flags)
"""
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")

    try:
        subprocess.Popen(
            [
                powershell,
                "-NoProfile",
                "-WindowStyle",
                "Hidden",
                "-EncodedCommand",
                encoded,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        logger.info("notify: used Windows popup fallback for %s", title)
        return True
    except Exception as e:
        logger.warning("notify: Windows popup fallback failed (%s): %s", title, e)
        return False


def clear_notifications() -> bool:
    """Best-effort clear of notifications created under the Spark app id."""
    if sys.platform != "win32":
        return False
    try:
        from windows_toasts import WindowsToaster
        for app_id in ("Spark AI", "SPARK AI Assistant", "AI Assistant"):
            try:
                WindowsToaster(app_id).clear_toasts()
            except Exception:
                pass
        return True
    except Exception as e:
        logger.debug("notify: clear_notifications failed: %s", e)
        return False


def notify_stage_change(adapter_name: str, stage: str, guidance: Optional[str]) -> bool:
    """Convenience wrapper for checkout-stage transitions.

    The watcher calls this on every CHECKOUT_STAGE_CHANGED event. We
    deduplicate friendly titles per stage so the notifications read like
    a coherent step-by-step rather than a wall of identical popups.
    """
    success_title = (
        f"{adapter_name.capitalize()} — Booking confirmed"
        if adapter_name.lower() == "booking"
        else f"{adapter_name.capitalize()} — Order placed"
    )
    titles = {
        "shipping": f"{adapter_name.capitalize()} — Step 1 of 3",
        "shipping_ready": f"{adapter_name.capitalize()} — Click Proceed to Pay",
        "confirm":  f"{adapter_name.capitalize()} — Step 2 of 3",
        "gateway":  f"{adapter_name.capitalize()} — Step 3 of 3",
        "search": f"{adapter_name.capitalize()} — Choose Hotel",
        "property": f"{adapter_name.capitalize()} — Review Property",
        "availability": f"{adapter_name.capitalize()} — Choose Room",
        "details": f"{adapter_name.capitalize()} — Booking Details",
        "payment": f"{adapter_name.capitalize()} — Payment",
        "success":  success_title,
        "unknown":  f"{adapter_name.capitalize()}",
    }
    title = titles.get(stage, adapter_name.capitalize())
    body = guidance or f"Now at {stage}"
    return notify(title, body, sound=True)


__all__ = ["notify", "notify_stage_change", "clear_notifications", "is_available"]
