from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

_toaster: Optional[Any] = None
_toasts_checked = False
_toasts_available = False
_InteractableWindowsToaster: Any = None
_Toast: Any = None
_ToastButton: Any = None


def _toasts_enabled() -> bool:
    try:
        from app.config import settings

        return bool(getattr(settings, "DESKTOP_TOASTS_ENABLED", True))
    except Exception:
        return True


def _ensure_toasts_loaded() -> bool:
    global _toasts_checked
    global _toasts_available
    global _InteractableWindowsToaster
    global _Toast
    global _ToastButton

    if _toasts_checked:
        return _toasts_available

    _toasts_checked = True
    if not _toasts_enabled():
        logger.info("Desktop toast notifications disabled by config.")
        _toasts_available = False
        return False

    try:
        from windows_toasts import InteractableWindowsToaster, Toast, ToastButton
    except Exception as exc:
        logger.warning(
            "windows-toasts unavailable. Desktop notifications will fallback to logs: %s",
            exc,
        )
        _toasts_available = False
        return False

    _InteractableWindowsToaster = InteractableWindowsToaster
    _Toast = Toast
    _ToastButton = ToastButton
    _toasts_available = True
    return True


def _get_toaster() -> Optional[Any]:
    global _toaster
    if not _ensure_toasts_loaded():
        return None
    if _toaster is None:
        _toaster = _InteractableWindowsToaster("SPARK AI Assistant")
    return _toaster


def _run_callback_async(callback: Callable[[str, str, bool], Awaitable[None]], user_id: str, task_id: str, approved: bool) -> None:
    threading.Thread(
        target=lambda: asyncio.run(callback(user_id, task_id, approved)),
        daemon=True,
    ).start()


def show_approval_notification(
    user_id: str,
    task_id: str,
    question: str,
    on_response_callback: Optional[Callable[[str, str, bool], Awaitable[None]]] = None,
) -> None:
    """Show desktop approval toast; falls back to auto-approve if unavailable."""
    toaster = _get_toaster()
    if toaster is None:
        logger.info("[NOTIFICATION] Approval needed for %s: %s", task_id, question)
        if on_response_callback:
            _run_callback_async(on_response_callback, user_id, task_id, True)
        return

    try:
        toast = _Toast()
        toast.text_fields = ["SPARK AI - Approval Required", question]
        toast.AddAction(_ToastButton("Accept", arguments=f"approve|{user_id}|{task_id}"))
        toast.AddAction(_ToastButton("Deny", arguments=f"deny|{user_id}|{task_id}"))

        def on_activated(event: Any) -> None:
            args = event.arguments or ""
            parts = args.split("|")
            if len(parts) != 3:
                return
            action, uid, tid = parts
            approved = action == "approve"
            if on_response_callback:
                asyncio.run(on_response_callback(uid, tid, approved))

        def on_dismissed(_: Any) -> None:
            if on_response_callback:
                asyncio.run(on_response_callback(user_id, task_id, False))

        toast.on_activated = on_activated
        toast.on_dismissed = on_dismissed
        toaster.show_toast(toast)
    except Exception as exc:
        logger.error("Failed to show approval notification: %s", exc)
        if on_response_callback:
            _run_callback_async(on_response_callback, user_id, task_id, True)


def show_info_notification(title: str, message: str) -> None:
    """Show non-interactive desktop toast; logs when unavailable."""
    toaster = _get_toaster()
    if toaster is None:
        logger.info("[NOTIFICATION] %s: %s", title, message)
        return
    try:
        toast = _Toast()
        toast.text_fields = [title, message]
        toaster.show_toast(toast)
    except Exception as exc:
        logger.error("Failed to show info notification: %s", exc)
