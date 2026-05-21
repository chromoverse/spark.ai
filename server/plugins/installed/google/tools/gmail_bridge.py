"""Bridge-wrapped Gmail tools — gmail_read and gmail_send.

These go through ExternalActionBridge for rate limiting and audit logging.
"""
from __future__ import annotations

from typing import Any, Dict

from app.plugins.tools.tool_base import BaseTool, ToolOutput


class GmailReadTool(BaseTool):
    """Read/list emails via the external action bridge."""

    # ── Plugin-shipped tool metadata ────────────────────────────────────
    TOOL_DESCRIPTION = "Read/list emails via the external action bridge with rate limiting and audit logging"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA: Dict[str, Any] = {
        "query": {"type": "string", "required": False, "description": "Gmail search query e.g. 'is:unread', 'from:boss@corp.com'"},
        "max_results": {"type": "integer", "required": False, "default": 10},
    }
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {"emails": {"type": "array"}, "total_returned": {"type": "integer"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "check my email", "inputs": {}}]
    SEMANTIC_TAGS = ["gmail", "email", "read", "inbox", "check"]
    TOOL_CATEGORY = "communication"

    def get_tool_name(self) -> str:
        return "gmail_read"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "").strip()
        if not user_id:
            return ToolOutput(success=False, data={}, error="user_id required")

        query = self.get_input(inputs, "query", "")
        max_results = int(self.get_input(inputs, "max_results", 10) or 10)

        from app.features.bridge.action_bridge import get_action_bridge

        async def _handler(user_id=user_id, query=query, max_results=max_results):
            from app.features.gmail._client import get_gmail_service
            service = await get_gmail_service(user_id)
            kwargs: Dict[str, Any] = {"userId": "me", "maxResults": max_results, "labelIds": ["INBOX"]}
            if query:
                kwargs["q"] = query
            resp = service.users().messages().list(**kwargs).execute()
            messages_meta = resp.get("messages", [])
            emails = []
            for meta in messages_meta:
                msg = service.users().messages().get(
                    userId="me", id=meta["id"], format="metadata",
                    metadataHeaders=["From", "To", "Subject", "Date"],
                ).execute()
                headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
                emails.append({
                    "id": msg["id"],
                    "snippet": msg.get("snippet", ""),
                    "from": headers.get("From", ""),
                    "subject": headers.get("Subject", "(no subject)"),
                    "date": headers.get("Date", ""),
                    "is_read": "UNREAD" not in msg.get("labelIds", []),
                })
            return {"emails": emails, "total_returned": len(emails)}

        result = await get_action_bridge().execute(
            service="gmail", action="read_emails", user_id=user_id, handler=_handler,
        )
        if not result.success:
            return ToolOutput(success=False, data={}, error=result.error)
        return ToolOutput(success=True, data=result.data)


class GmailSendTool(BaseTool):
    """Send an email via the external action bridge."""

    # ── Plugin-shipped tool metadata ────────────────────────────────────
    TOOL_DESCRIPTION = "Send an email via the external action bridge with rate limiting and audit logging"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA: Dict[str, Any] = {
        "to": {"type": "string", "required": True},
        "subject": {"type": "string", "required": True},
        "body": {"type": "string", "required": True},
    }
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {"message_id": {"type": "string"}, "to": {"type": "string"}, "subject": {"type": "string"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "send an email to john@example.com about the meeting", "inputs": {"to": "john@example.com", "subject": "Meeting", "body": "Hi John, just following up about the meeting."}}]
    SEMANTIC_TAGS = ["gmail", "email", "send", "compose"]
    TOOL_CATEGORY = "communication"

    def get_tool_name(self) -> str:
        return "gmail_send"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "").strip()
        if not user_id:
            return ToolOutput(success=False, data={}, error="user_id required")

        to = self.get_input(inputs, "to", "")
        subject = self.get_input(inputs, "subject", "")
        body = self.get_input(inputs, "body", "")

        if not to or not subject or not body:
            return ToolOutput(success=False, data={}, error="to, subject, and body are required")

        from app.features.bridge.action_bridge import get_action_bridge

        async def _handler(user_id=user_id, to=to, subject=subject, body=body):
            import base64
            from email.mime.text import MIMEText
            from app.features.gmail._client import get_gmail_service

            service = await get_gmail_service(user_id)
            msg = MIMEText(body)
            msg["to"] = to
            msg["subject"] = subject
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
            return {"message_id": sent["id"], "to": to, "subject": subject}

        result = await get_action_bridge().execute(
            service="gmail", action="send_email", user_id=user_id, handler=_handler,
        )
        if not result.success:
            return ToolOutput(success=False, data={}, error=result.error)
        return ToolOutput(success=True, data=result.data)


__all__ = ["GmailReadTool", "GmailSendTool"]
