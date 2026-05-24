"""'Organize my day' — aggregate data from all connected services."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

from app.connectors.registry import get_all_connector_statuses
from app.plugins.tools.tool_base import BaseTool, ToolOutput

logger = logging.getLogger(__name__)


class OrganizeDayTool(BaseTool):
    """
    Pull today's data from all connected services into one summary.

    Internally calls: email_list, calendar_list_events, slack unread, etc.
    Only calls services the user has actually connected.
    """

    TOOL_DESCRIPTION = "Aggregate today's emails, calendar, tasks, and messages from all connected services"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA = {
        "user_id": {"type": "string", "required": True},
    }
    OUTPUT_SCHEMA = {
        "success": {"type": "boolean"},
        "data": {"summary": {"type": "object"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [
        {"user_utterance": "organize my day"},
        {"user_utterance": "what do I have today"},
        {"user_utterance": "morning briefing"},
        {"user_utterance": "what's on my plate today"},
    ]
    SEMANTIC_TAGS = ["organize", "day", "summary", "today", "overview", "morning", "briefing"]
    TOOL_CATEGORY = "productivity"
    METADATA: Dict[str, Any] = {"summary_tts": True}

    def get_tool_name(self) -> str:
        return "organize_day"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "").strip()
        if not user_id:
            return ToolOutput(success=False, data={}, error="user_id required")

        # Check what's connected
        statuses = await get_all_connector_statuses(user_id)
        connected = {s["id"] for s in statuses if s["connected"]}

        summary: Dict[str, Any] = {}
        tasks: List[asyncio.Task] = []
        task_keys: List[str] = []

        # Fan out to connected services in parallel
        if "gmail" in connected:
            tasks.append(asyncio.create_task(self._get_emails(user_id)))
            task_keys.append("email")
        if "google_calendar" in connected:
            tasks.append(asyncio.create_task(self._get_calendar(user_id)))
            task_keys.append("calendar")
        if "slack" in connected:
            tasks.append(asyncio.create_task(self._get_slack(user_id)))
            task_keys.append("slack")

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for key, result in zip(task_keys, results):
            if not isinstance(result, Exception):
                summary[key] = result
            else:
                logger.warning("organize_day: %s fetch failed: %s", key, result)
                summary[key] = {"error": str(result)}

        summary["connected_services"] = sorted(connected)
        summary["service_count"] = len(connected)

        return ToolOutput(success=True, data={"summary": summary})

    async def _get_emails(self, user_id: str) -> dict:
        from app.connectors.clients.gmail import get_gmail_service
        service = await get_gmail_service(user_id)
        resp = service.users().messages().list(
            userId="me", labelIds=["INBOX", "UNREAD"], maxResults=5
        ).execute()
        count = resp.get("resultSizeEstimate", 0)
        return {"unread_count": count, "preview": resp.get("messages", [])[:3]}

    async def _get_calendar(self, user_id: str) -> dict:
        from app.connectors.clients.calendar import get_calendar_service
        from datetime import datetime, timedelta
        service = await get_calendar_service(user_id)
        now = datetime.utcnow()
        resp = service.events().list(
            calendarId="primary",
            timeMin=now.isoformat() + "Z",
            timeMax=(now + timedelta(days=1)).isoformat() + "Z",
            maxResults=10, singleEvents=True, orderBy="startTime",
        ).execute()
        events = [{
            "summary": e.get("summary", ""),
            "start": e.get("start", {}).get("dateTime", ""),
        } for e in resp.get("items", [])]
        return {"event_count": len(events), "events": events}

    async def _get_slack(self, user_id: str) -> dict:
        # Return connected status — detailed fetch requires channel selection
        return {"connected": True, "note": "Slack connected — ask about specific channels"}


__all__ = ["OrganizeDayTool"]
