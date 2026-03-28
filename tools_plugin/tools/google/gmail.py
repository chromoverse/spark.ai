"""
Gmail tools — list, read, send, reply, delete, trash, mark read/unread,
search, label, and move emails.

Every tool accepts `user_id` in its inputs to automatically fetch the Gmail service.
Example:

    result = await SomeTool().execute({"user_id": "...", ...})
"""

from __future__ import annotations

import base64
import logging
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

from ..base import BaseTool, ToolOutput  # adjust relative import as needed

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

async def _svc(inputs: Dict[str, Any]):
    """Extract or auto-fetch the Gmail service object from inputs."""
    service = inputs.get("service")
    if service is not None:
        return service
    
    user_id = inputs.get("user_id")
    if not user_id:
        raise ValueError("inputs['service'] or inputs['user_id'] is required to authenticate Gmail API.")
    
    from tools_plugin.utils.service_client import get_gmail_service
    account_email = inputs.get("account_email")
    return await get_gmail_service(user_id=user_id, account_email=account_email)


def _parse_headers(headers: List[Dict]) -> Dict[str, str]:
    """Convert Gmail header list → plain dict (case-preserved keys)."""
    return {h["name"]: h["value"] for h in headers}


def _decode_body(payload: Dict) -> str:
    """
    Recursively extract plain-text (preferred) or HTML body from a message payload.
    Returns an empty string if nothing is found.
    """
    mime = payload.get("mimeType", "")

    # Leaf node
    if mime in ("text/plain", "text/html"):
        data = payload.get("body", {}).get("data", "")
        if data:
            text = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
            if mime == "text/html":
                # strip tags for a readable preview
                text = re.sub(r"<[^>]+>", "", text)
            return text.strip()

    # multipart/* — recurse, prefer plain over html
    parts = payload.get("parts", [])
    plain, html = "", ""
    for part in parts:
        result = _decode_body(part)
        if part.get("mimeType") == "text/plain" and result:
            plain = result
        elif part.get("mimeType") == "text/html" and result:
            html = result
        elif result:  # nested multipart
            plain = plain or result

    return plain or html


def _build_message(
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = "",
    reply_to_message_id: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a raw RFC-2822 message dict ready for the Gmail API."""
    msg = MIMEMultipart("alternative")
    msg["To"] = to
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = cc
    if bcc:
        msg["Bcc"] = bcc
    if reply_to_message_id:
        msg["In-Reply-To"] = reply_to_message_id
        msg["References"] = reply_to_message_id

    msg.attach(MIMEText(body, "plain", "utf-8"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    payload: Dict[str, Any] = {"raw": raw}
    if thread_id:
        payload["threadId"] = thread_id
    return payload


# ===========================================================================
# Tool 1 — email_list
# ===========================================================================

class EmailListTool(BaseTool):
    """
    List emails from the user's mailbox.

    Inputs:
    - user_id (str, required): The user's ID
    - label_ids (list, optional): Label IDs to filter by (default: ["INBOX"])
    - query (str, optional): Gmail search syntax
    - max_results (int, optional): Max emails to return (default: 20)

    Outputs:
    - emails (list): Lightweight summary list with snippet, subject, sender, date
    - total_returned (int)
    - next_page_token (str, optional)
    """

    def get_tool_name(self) -> str:
        return "email_list"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            service = await _svc(inputs)
            label_ids: List[str] = inputs.get("label_ids", ["INBOX"])
            query: str = inputs.get("query", "")
            max_results: int = int(inputs.get("max_results", 20))

            kwargs: Dict[str, Any] = {
                "userId": "me",
                "maxResults": max_results,
                "labelIds": label_ids,
            }
            if query:
                kwargs["q"] = query

            resp = service.users().messages().list(**kwargs).execute()
            messages_meta = resp.get("messages", [])

            emails = []
            for meta in messages_meta:
                msg = (
                    service.users()
                    .messages()
                    .get(userId="me", id=meta["id"], format="metadata",
                         metadataHeaders=["From", "To", "Subject", "Date"])
                    .execute()
                )
                headers = _parse_headers(msg.get("payload", {}).get("headers", []))
                emails.append({
                    "id": msg["id"],
                    "thread_id": msg.get("threadId"),
                    "labels": msg.get("labelIds", []),
                    "snippet": msg.get("snippet", ""),
                    "from": headers.get("From", ""),
                    "to": headers.get("To", ""),
                    "subject": headers.get("Subject", "(no subject)"),
                    "date": headers.get("Date", ""),
                    "is_read": "UNREAD" not in msg.get("labelIds", []),
                })

            return ToolOutput(
                success=True,
                data={
                    "emails": emails,
                    "total_returned": len(emails),
                    "next_page_token": resp.get("nextPageToken"),
                },
            )
        except Exception as exc:
            self.logger.error("email_list error: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))


# ===========================================================================
# Tool 2 — email_read
# ===========================================================================

class EmailReadTool(BaseTool):
    """
    Fetch the full content of a single email by message ID.

    Inputs:
    - user_id (str, required): The user's ID
    - message_id (str, required): The ID of the message to read

    Outputs:
    - id, thread_id, labels, is_read
    - from, to, cc, subject, date
    - body (str): Full text or HTML body
    - snippet (str)
    - attachments (list): Metadata of attachments
    """

    def get_tool_name(self) -> str:
        return "email_read"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            service = await _svc(inputs)
            message_id: str = inputs["message_id"]

            msg = (
                service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )

            headers = _parse_headers(msg.get("payload", {}).get("headers", []))
            body = _decode_body(msg.get("payload", {}))

            # Collect attachment metadata (don't download automatically)
            attachments = []
            for part in msg.get("payload", {}).get("parts", []):
                filename = part.get("filename", "")
                if filename:
                    attachments.append({
                        "filename": filename,
                        "mime_type": part.get("mimeType"),
                        "attachment_id": part.get("body", {}).get("attachmentId"),
                        "size_bytes": part.get("body", {}).get("size", 0),
                    })

            return ToolOutput(
                success=True,
                data={
                    "id": msg["id"],
                    "thread_id": msg.get("threadId"),
                    "labels": msg.get("labelIds", []),
                    "is_read": "UNREAD" not in msg.get("labelIds", []),
                    "from": headers.get("From", ""),
                    "to": headers.get("To", ""),
                    "cc": headers.get("Cc", ""),
                    "subject": headers.get("Subject", "(no subject)"),
                    "date": headers.get("Date", ""),
                    "body": body,
                    "snippet": msg.get("snippet", ""),
                    "attachments": attachments,
                },
            )
        except Exception as exc:
            self.logger.error("email_read error: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))


# ===========================================================================
# Tool 3 — email_send
# ===========================================================================

class EmailSendTool(BaseTool):
    """
    Compose and send a new email.

    Inputs:
    - user_id (str, required): The user's ID
    - to (str, required): Recipient email address
    - subject (str, required): Email subject
    - body (str, required): Email body
    - cc (str, optional): CC addresses
    - bcc (str, optional): BCC addresses

    Outputs:
    - message_id (str)
    - thread_id (str)
    - labels (list)
    """

    def get_tool_name(self) -> str:
        return "email_send"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            service = await _svc(inputs)
            to: str = inputs["to"]
            subject: str = inputs["subject"]
            body: str = inputs["body"]
            cc: str = inputs.get("cc", "")
            bcc: str = inputs.get("bcc", "")

            raw_msg = _build_message(to=to, subject=subject, body=body, cc=cc, bcc=bcc)

            sent = service.users().messages().send(userId="me", body=raw_msg).execute()

            return ToolOutput(
                success=True,
                data={
                    "message_id": sent["id"],
                    "thread_id": sent.get("threadId"),
                    "to": to,
                    "subject": subject,
                    "labels": sent.get("labelIds", []),
                },
            )
        except Exception as exc:
            self.logger.error("email_send error: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))


# ===========================================================================
# Tool 4 — email_reply
# ===========================================================================

class EmailReplyTool(BaseTool):
    """
    Reply to an existing email (stays in the same thread).

    Looks up the original message to populate To/Subject automatically
    unless overridden.

    Inputs:
    - user_id (str, required): The user's ID
    - message_id (str, required): The original message ID to reply to
    - body (str, required): The reply body
    - to (str, optional): Override recipient
    - subject (str, optional): Override subject

    Outputs:
    - message_id, thread_id, replied_to, to, subject
    """

    def get_tool_name(self) -> str:
        return "email_reply"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            service = await _svc(inputs)
            message_id: str = inputs["message_id"]
            body: str = inputs["body"]

            # Fetch original to get thread metadata
            orig = (
                service.users()
                .messages()
                .get(userId="me", id=message_id, format="metadata",
                     metadataHeaders=["From", "To", "Subject", "Message-ID"])
                .execute()
            )
            orig_headers = _parse_headers(orig.get("payload", {}).get("headers", []))
            thread_id: str = orig.get("threadId", "")

            to: str = inputs.get("to") or orig_headers.get("From", "")
            subject: str = inputs.get("subject") or (
                "Re: " + orig_headers.get("Subject", "").lstrip("Re: ")
            )
            orig_msg_id = orig_headers.get("Message-ID", "")

            raw_msg = _build_message(
                to=to,
                subject=subject,
                body=body,
                reply_to_message_id=orig_msg_id,
                thread_id=thread_id,
            )

            sent = service.users().messages().send(userId="me", body=raw_msg).execute()

            return ToolOutput(
                success=True,
                data={
                    "message_id": sent["id"],
                    "thread_id": sent.get("threadId"),
                    "replied_to": message_id,
                    "to": to,
                    "subject": subject,
                },
            )
        except Exception as exc:
            self.logger.error("email_reply error: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))


# ===========================================================================
# Tool 5 — email_delete  (permanent)
# ===========================================================================

class EmailDeleteTool(BaseTool):
    """
    Permanently delete an email (bypasses Trash).
    Use email_trash for a safer, reversible move-to-trash.

    Inputs:
    - user_id (str, required): The user's ID
    - message_id (str, required): The message ID to delete

    Outputs:
    - deleted_message_id (str)
    - permanent (bool): True
    """

    def get_tool_name(self) -> str:
        return "email_delete"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            service = await _svc(inputs)
            message_id: str = inputs["message_id"]

            service.users().messages().delete(userId="me", id=message_id).execute()

            return ToolOutput(
                success=True,
                data={"deleted_message_id": message_id, "permanent": True},
            )
        except Exception as exc:
            self.logger.error("email_delete error: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))


# ===========================================================================
# Tool 6 — email_trash
# ===========================================================================

class EmailTrashTool(BaseTool):
    """
    Move an email to the Gmail Trash (recoverable for 30 days).

    Inputs:
    - user_id (str, required): The user's ID
    - message_id (str, required): The message ID to trash

    Outputs:
    - message_id (str)
    - labels (list)
    - trashed (bool): True
    """

    def get_tool_name(self) -> str:
        return "email_trash"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            service = await _svc(inputs)
            message_id: str = inputs["message_id"]

            msg = (
                service.users().messages().trash(userId="me", id=message_id).execute()
            )

            return ToolOutput(
                success=True,
                data={
                    "message_id": msg["id"],
                    "labels": msg.get("labelIds", []),
                    "trashed": True,
                },
            )
        except Exception as exc:
            self.logger.error("email_trash error: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))


# ===========================================================================
# Tool 7 — email_mark_read
# ===========================================================================

class EmailMarkReadTool(BaseTool):
    """
    Mark one or more emails as read (removes the UNREAD label).

    Inputs:
    - user_id (str, required): The user's ID
    - message_ids (list, required): A list of message IDs

    Outputs:
    - marked_read (list): Updated messages info
    - count (int): Number of updated messages
    """

    def get_tool_name(self) -> str:
        return "email_mark_read"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            service = await _svc(inputs)
            message_ids: List[str] = inputs["message_ids"]

            updated = []
            for mid in message_ids:
                msg = (
                    service.users()
                    .messages()
                    .modify(
                        userId="me",
                        id=mid,
                        body={"removeLabelIds": ["UNREAD"]},
                    )
                    .execute()
                )
                updated.append({"id": msg["id"], "labels": msg.get("labelIds", [])})

            return ToolOutput(
                success=True,
                data={"marked_read": updated, "count": len(updated)},
            )
        except Exception as exc:
            self.logger.error("email_mark_read error: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))


# ===========================================================================
# Tool 8 — email_mark_unread
# ===========================================================================

class EmailMarkUnreadTool(BaseTool):
    """
    Mark one or more emails as unread (adds the UNREAD label).

    Inputs:
    - user_id (str, required): The user's ID
    - message_ids (list, required): A list of message IDs

    Outputs:
    - marked_unread (list): Updated messages info
    - count (int): Number of updated messages
    """

    def get_tool_name(self) -> str:
        return "email_mark_unread"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            service = await _svc(inputs)
            message_ids: List[str] = inputs["message_ids"]

            updated = []
            for mid in message_ids:
                msg = (
                    service.users()
                    .messages()
                    .modify(
                        userId="me",
                        id=mid,
                        body={"addLabelIds": ["UNREAD"]},
                    )
                    .execute()
                )
                updated.append({"id": msg["id"], "labels": msg.get("labelIds", [])})

            return ToolOutput(
                success=True,
                data={"marked_unread": updated, "count": len(updated)},
            )
        except Exception as exc:
            self.logger.error("email_mark_unread error: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))


# ===========================================================================
# Tool 9 — email_search
# ===========================================================================

class EmailSearchTool(BaseTool):
    """
    Search emails using full Gmail search syntax
    (e.g. "from:boss@corp.com is:unread after:2024/01/01").

    Inputs:
    - user_id (str, required): The user's ID
    - query (str, required): Gmail search syntax
    - max_results (int, optional): Max emails to return (default: 20)

    Outputs:
    - query (str)
    - emails (list): Search results summary
    - total_returned (int)
    - next_page_token (str, optional)
    """

    def get_tool_name(self) -> str:
        return "email_search"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            service = await _svc(inputs)
            query: str = inputs["query"]
            max_results: int = int(inputs.get("max_results", 20))

            resp = (
                service.users()
                .messages()
                .list(userId="me", q=query, maxResults=max_results)
                .execute()
            )
            messages_meta = resp.get("messages", [])

            emails = []
            for meta in messages_meta:
                msg = (
                    service.users()
                    .messages()
                    .get(userId="me", id=meta["id"], format="metadata",
                         metadataHeaders=["From", "To", "Subject", "Date"])
                    .execute()
                )
                headers = _parse_headers(msg.get("payload", {}).get("headers", []))
                emails.append({
                    "id": msg["id"],
                    "thread_id": msg.get("threadId"),
                    "labels": msg.get("labelIds", []),
                    "is_read": "UNREAD" not in msg.get("labelIds", []),
                    "snippet": msg.get("snippet", ""),
                    "from": headers.get("From", ""),
                    "to": headers.get("To", ""),
                    "subject": headers.get("Subject", "(no subject)"),
                    "date": headers.get("Date", ""),
                })

            return ToolOutput(
                success=True,
                data={
                    "query": query,
                    "emails": emails,
                    "total_returned": len(emails),
                    "next_page_token": resp.get("nextPageToken"),
                },
            )
        except Exception as exc:
            self.logger.error("email_search error: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))


# ===========================================================================
# Tool 10 — email_label
# ===========================================================================

class EmailLabelTool(BaseTool):
    """
    Add or remove Gmail labels on an email.
    Works with built-in labels (STARRED, IMPORTANT, …) and custom ones.
    Pass label names; the tool resolves them to IDs automatically.

    Inputs:
    - user_id (str, required): The user's ID
    - message_id (str, required): The message ID
    - add_labels (list, optional): Label names to add
    - remove_labels (list, optional): Label names to remove

    Outputs:
    - message_id, labels, added, removed
    """

    def get_tool_name(self) -> str:
        return "email_label"

    # Cache label name → id within a single tool instance lifetime
    _label_cache: Dict[str, str] = {}

    def _resolve_label_ids(self, service, names: List[str]) -> List[str]:
        """Map human-readable label names to Gmail label IDs."""
        if not self._label_cache:
            all_labels = (
                service.users().labels().list(userId="me").execute().get("labels", [])
            )
            self._label_cache = {lbl["name"].upper(): lbl["id"] for lbl in all_labels}
            # also index by id for pass-through
            self._label_cache.update({lbl["id"]: lbl["id"] for lbl in all_labels})

        ids = []
        for name in names:
            resolved = self._label_cache.get(name.upper()) or self._label_cache.get(name)
            if resolved:
                ids.append(resolved)
            else:
                logger.warning("Label not found, skipping: %s", name)
        return ids

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            service = await _svc(inputs)
            message_id: str = inputs["message_id"]
            add_labels: List[str] = inputs.get("add_labels", [])
            remove_labels: List[str] = inputs.get("remove_labels", [])

            body: Dict[str, List[str]] = {}
            if add_labels:
                body["addLabelIds"] = self._resolve_label_ids(service, add_labels)
            if remove_labels:
                body["removeLabelIds"] = self._resolve_label_ids(service, remove_labels)

            msg = (
                service.users()
                .messages()
                .modify(userId="me", id=message_id, body=body)
                .execute()
            )

            return ToolOutput(
                success=True,
                data={
                    "message_id": msg["id"],
                    "labels": msg.get("labelIds", []),
                    "added": add_labels,
                    "removed": remove_labels,
                },
            )
        except Exception as exc:
            self.logger.error("email_label error: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))


# ===========================================================================
# Tool 11 — email_move
# ===========================================================================

class EmailMoveTool(BaseTool):
    """
    Move an email to a different label / folder.
    Adds the destination label and removes INBOX (and any other
    specified source labels) in one API call.

    Inputs:
    - user_id (str, required): The user's ID
    - message_id (str, required): The message ID
    - destination (str, required): Target label name or ID
    - remove_from (list, optional): Source labels to remove (default: ["INBOX"])

    Outputs:
    - message_id, labels, moved_to, removed_from
    """

    def get_tool_name(self) -> str:
        return "email_move"

    def _get_label_id(self, service, name: str) -> Optional[str]:
        all_labels = (
            service.users().labels().list(userId="me").execute().get("labels", [])
        )
        name_upper = name.upper()
        for lbl in all_labels:
            if lbl["name"].upper() == name_upper or lbl["id"] == name:
                return lbl["id"]
        return None

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            service = await _svc(inputs)
            message_id: str = inputs["message_id"]
            destination: str = inputs["destination"]          # label name or id
            remove_from: List[str] = inputs.get("remove_from", ["INBOX"])

            dest_id = self._get_label_id(service, destination)
            if not dest_id:
                return ToolOutput(
                    success=False,
                    data={},
                    error=f"Destination label not found: {destination}",
                )

            remove_ids = []
            for src in remove_from:
                lid = self._get_label_id(service, src)
                if lid:
                    remove_ids.append(lid)

            msg = (
                service.users()
                .messages()
                .modify(
                    userId="me",
                    id=message_id,
                    body={"addLabelIds": [dest_id], "removeLabelIds": remove_ids},
                )
                .execute()
            )

            return ToolOutput(
                success=True,
                data={
                    "message_id": msg["id"],
                    "labels": msg.get("labelIds", []),
                    "moved_to": destination,
                    "removed_from": remove_from,
                },
            )
        except Exception as exc:
            self.logger.error("email_move error: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))


# ===========================================================================
# Tool 12 — email_organize
# ===========================================================================

class EmailOrganizeTool(BaseTool):
    """
    Bulk-organize emails that match a Gmail search query.

    Actions:
      - mark_read      → remove UNREAD from all matches
      - mark_unread    → add UNREAD to all matches
      - archive        → remove INBOX label (keeps email, removes from inbox)
      - trash          → move all matches to Trash
      - label:<name>   → add a label to all matches
      - unlabel:<name> → remove a label from all matches

    Inputs:
    - user_id (str, required): The user's ID
    - query (str, required): Gmail search query to match
    - action (str, required): Organization action string
    - max_messages (int, optional): Max messages to process (default: 50)

    Outputs:
    - action, query, affected_count (int)
    """

    def get_tool_name(self) -> str:
        return "email_organize"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            service = await _svc(inputs)
            query: str = inputs["query"]
            action: str = inputs["action"]
            max_messages: int = int(inputs.get("max_messages", 50))

            # Gather matching message IDs
            resp = (
                service.users()
                .messages()
                .list(userId="me", q=query, maxResults=max_messages)
                .execute()
            )
            message_ids = [m["id"] for m in resp.get("messages", [])]

            if not message_ids:
                return ToolOutput(
                    success=True,
                    data={"action": action, "query": query, "affected_count": 0,
                          "message": "No messages matched the query."},
                )

            # Resolve the action
            add_ids: List[str] = []
            remove_ids: List[str] = []

            if action == "mark_read":
                remove_ids = ["UNREAD"]
            elif action == "mark_unread":
                add_ids = ["UNREAD"]
            elif action == "archive":
                remove_ids = ["INBOX"]
            elif action == "trash":
                for mid in message_ids:
                    service.users().messages().trash(userId="me", id=mid).execute()
                return ToolOutput(
                    success=True,
                    data={"action": action, "query": query,
                          "affected_count": len(message_ids)},
                )
            elif action.startswith("label:"):
                label_name = action.split(":", 1)[1]
                all_labels = (
                    service.users().labels().list(userId="me")
                    .execute().get("labels", [])
                )
                for lbl in all_labels:
                    if lbl["name"].upper() == label_name.upper():
                        add_ids = [lbl["id"]]
                        break
                if not add_ids:
                    return ToolOutput(
                        success=False, data={},
                        error=f"Label not found: {label_name}",
                    )
            elif action.startswith("unlabel:"):
                label_name = action.split(":", 1)[1]
                all_labels = (
                    service.users().labels().list(userId="me")
                    .execute().get("labels", [])
                )
                for lbl in all_labels:
                    if lbl["name"].upper() == label_name.upper():
                        remove_ids = [lbl["id"]]
                        break
                if not remove_ids:
                    return ToolOutput(
                        success=False, data={},
                        error=f"Label not found: {label_name}",
                    )
            else:
                return ToolOutput(
                    success=False, data={},
                    error=f"Unknown action: '{action}'. Valid: mark_read, mark_unread, archive, trash, label:<name>, unlabel:<name>",
                )

            # Apply via batchModify for efficiency
            service.users().messages().batchModify(
                userId="me",
                body={
                    "ids": message_ids,
                    "addLabelIds": add_ids,
                    "removeLabelIds": remove_ids,
                },
            ).execute()

            return ToolOutput(
                success=True,
                data={
                    "action": action,
                    "query": query,
                    "affected_count": len(message_ids),
                },
            )
        except Exception as exc:
            self.logger.error("email_organize error: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))


# ===========================================================================
# Tool 13 — email_labels_list
# ===========================================================================

class EmailLabelsListTool(BaseTool):
    """
    Return all Gmail labels (system + user-created) for the account.
    Useful for building a folder/label picker UI or resolving names to IDs.

    Inputs:
    - user_id (str, required): The user's ID

    Outputs:
    - labels (list): List of label dicts (id, name, type, messages_total, messages_unread)
    - total (int)
    """

    def get_tool_name(self) -> str:
        return "email_labels_list"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            service = await _svc(inputs)
            resp = service.users().labels().list(userId="me").execute()
            labels = [
                {
                    "id": lbl["id"],
                    "name": lbl["name"],
                    "type": lbl.get("type", "user"),
                    "messages_total": lbl.get("messagesTotal"),
                    "messages_unread": lbl.get("messagesUnread"),
                }
                for lbl in resp.get("labels", [])
            ]
            return ToolOutput(
                success=True,
                data={"labels": labels, "total": len(labels)},
            )
        except Exception as exc:
            self.logger.error("email_labels_list error: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))


# ===========================================================================
# Registration
# ===========================================================================

__all__ = [
    "EmailListTool",
    "EmailReadTool",
    "EmailSendTool",
    "EmailReplyTool",
    "EmailDeleteTool",
    "EmailTrashTool",
    "EmailMarkReadTool",
    "EmailMarkUnreadTool",
    "EmailSearchTool",
    "EmailLabelTool",
    "EmailMoveTool",
    "EmailOrganizeTool",
    "EmailLabelsListTool",
]