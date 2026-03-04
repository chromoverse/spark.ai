from __future__ import annotations

import asyncio
import logging
import threading
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

try:
    from windows_toasts import (
        InteractableWindowsToaster,
        Toast,
        ToastActivatedEventArgs,
        ToastButton,
        ToastDismissedEventArgs,
    )

    TOASTS_AVAILABLE = True
except ImportError:
    TOASTS_AVAILABLE = False
    logger.warning("windows-toasts not installed. Desktop notifications will fallback to logs.")


_toaster: Optional["InteractableWindowsToaster"] = None


def _get_toaster() -> "InteractableWindowsToaster":
    global _toaster
    if _toaster is None and TOASTS_AVAILABLE:
        _toaster = InteractableWindowsToaster("SPARK AI Assistant")
    return _toaster  # type: ignore[return-value]


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
    if not TOASTS_AVAILABLE:
        logger.info("[NOTIFICATION] Approval needed for %s: %s", task_id, question)
        if on_response_callback:
            _run_callback_async(on_response_callback, user_id, task_id, True)
        return

    try:
        toaster = _get_toaster()
        toast = Toast()
        toast.text_fields = ["SPARK AI - Approval Required", question]
        toast.AddAction(ToastButton("Accept", arguments=f"approve|{user_id}|{task_id}"))
        toast.AddAction(ToastButton("Deny", arguments=f"deny|{user_id}|{task_id}"))

        def on_activated(event: ToastActivatedEventArgs) -> None:
            args = event.arguments or ""
            parts = args.split("|")
            if len(parts) != 3:
                return
            action, uid, tid = parts
            approved = action == "approve"
            if on_response_callback:
                asyncio.run(on_response_callback(uid, tid, approved))

        def on_dismissed(_: ToastDismissedEventArgs) -> None:
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
    if not TOASTS_AVAILABLE:
        logger.info("[NOTIFICATION] %s: %s", title, message)
        return
    try:
        toaster = _get_toaster()
        toast = Toast()
        toast.text_fields = [title, message]
        toaster.show_toast(toast)
    except Exception as exc:
        logger.error("Failed to show info notification: %s", exc)
