# app/agent/client_core/notification.py
"""
Windows Toast Notification System for Desktop Mode

Shows native Windows 10/11 toast notifications with interactive buttons
for task approval requests. Uses the `windows-toasts` library.

Flow:
    Server → TaskEmitter → receive_approval_request() → show_approval_notification()
    User clicks Accept/Deny → _handle_response() → Orchestrator.handle_approval()
"""

import logging
import asyncio
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# Try to import windows-toasts
try:
    from windows_toasts import (
        Toast, 
        ToastDisplayImage,
        ToastButton,
        InteractableWindowsToaster,
        ToastActivatedEventArgs,
        ToastDismissedEventArgs
    )
    TOASTS_AVAILABLE = True
except ImportError:
    TOASTS_AVAILABLE = False
    logger.warning("⚠️ windows-toasts not installed. Notifications will be logged only.")


# Global toaster instance (reuse for performance)
_toaster: Optional['InteractableWindowsToaster'] = None


def _get_toaster() -> 'InteractableWindowsToaster':
    """Get or create the global toaster instance"""
    global _toaster
    if _toaster is None and TOASTS_AVAILABLE:
        _toaster = InteractableWindowsToaster("SPARK AI Assistant")
    return _toaster


def show_approval_notification(
    user_id: str, 
    task_id: str, 
    question: str,
    on_response_callback=None
) -> None:
    """
    Show a Windows toast notification requesting user approval.
    
    Args:
        user_id: User identifier
        task_id: Task identifier  
        question: The approval question to display
        on_response_callback: Optional async callback(user_id, task_id, approved: bool)
    """
    if not TOASTS_AVAILABLE:
        logger.info(f"📢 [NOTIFICATION] Approval needed for {task_id}: {question}")
        logger.info("   (windows-toasts not available, auto-approving)")
        # Auto-approve if no notification system
        if on_response_callback:
            threading.Thread(
                target=lambda: asyncio.run(on_response_callback(user_id, task_id, True)),
                daemon=True
            ).start()
        return
    
    try:
        toaster = _get_toaster()
        
        # Create toast
        toast = Toast()
        toast.text_fields = [
            "🤖 SPARK AI — Approval Required",
            question
        ]
        
        # Add Custom Icon
        import os
        # Try to find the icon
        icon_path = os.path.abspath(os.path.join(os.getcwd(), "public", "icon-high-ql.png"))
        if os.path.exists(icon_path):
            from windows_toasts import ToastDisplayImage
            toast.AddImage(ToastDisplayImage.fromPath(icon_path))
        
        # Add Accept and Deny buttons
        toast.AddAction(ToastButton("✅ Accept", arguments=f"approve|{user_id}|{task_id}"))
        toast.AddAction(ToastButton("❌ Deny", arguments=f"deny|{user_id}|{task_id}"))
        
        # Handle button clicks
        def on_activated(activated_event_args: ToastActivatedEventArgs):
            try:
                args = activated_event_args.arguments
                if not args:
                    logger.info("🔔 Notification clicked (no action)")
                    return
                
                parts = args.split("|")
                if len(parts) != 3:
                    logger.warning(f"⚠️ Invalid notification args: {args}")
                    return
                
                action, uid, tid = parts
                approved = action == "approve"
                
                logger.info(f"{'✅' if approved else '❌'} User {'approved' if approved else 'denied'} task {tid}")
                
                # Call the response callback 
                if on_response_callback:
                    # Run async callback in a new event loop (we're in a callback thread)
                    asyncio.run(on_response_callback(uid, tid, approved))
                    
            except Exception as e:
                logger.error(f"❌ Error handling notification response: {e}")
        
        def on_dismissed(dismissed_event_args: ToastDismissedEventArgs):
            logger.info(f"🔕 Notification dismissed for task {task_id}")
            # Treat dismissal as denial
            if on_response_callback:
                try:
                    asyncio.run(on_response_callback(user_id, task_id, False))
                except Exception as e:
                    logger.error(f"❌ Error handling dismissal: {e}")
        
        toast.on_activated = on_activated
        toast.on_dismissed = on_dismissed
        
        # Show the toast
        toaster.show_toast(toast)
        
        logger.info(f"🔔 Approval notification shown for task {task_id}")
        
    except Exception as e:
        logger.error(f"❌ Failed to show notification: {e}")
        # Fallback: auto-approve
        if on_response_callback:
            threading.Thread(
                target=lambda: asyncio.run(on_response_callback(user_id, task_id, True)),
                daemon=True
            ).start()


def show_info_notification(title: str, message: str) -> None:
    """
    Show a simple informational toast notification (no buttons).
    
    Args:
        title: Notification title
        message: Notification body
    """
    if not TOASTS_AVAILABLE:
        logger.info(f"📢 [NOTIFICATION] {title}: {message}")
        return
    
    try:
        toaster = _get_toaster()
        toast = Toast()
        toast.text_fields = [title, message]
        toaster.show_toast(toast)
        logger.info(f"🔔 Info notification: {title}")
    except Exception as e:
        logger.error(f"❌ Failed to show info notification: {e}")
