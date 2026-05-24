"""Google Calendar tools — list events, create event."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict

from app.connectors.clients.calendar import get_calendar_service
from app.plugins.tools.tool_base import BaseTool, ToolOutput

logger = logging.getLogger(__name__)


async def _svc(inputs: Dict[str, Any]):
    user_id = inputs.get("_user_id") or inputs.get("user_id")
    if not user_id:
        raise ValueError("user_id required")
    return await get_calendar_service(user_id=str(user_id))


class CalendarListEventsTool(BaseTool):
    """
    List upcoming calendar events.

    Inputs:
    - user_id (string, required)
    - days_ahead (integer, optional): How many days to look ahead (default: 1)
    - max_results (integer, optional): Max events to return (default: 10)

    Outputs:
    - events (array): [{summary, start, end, location, description, id}]
    - total (integer)
    """

    TOOL_DESCRIPTION = "List upcoming calendar events for today or coming days"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA = {
        "user_id": {"type": "string", "required": True},
        "days_ahead": {"type": "integer", "required": False, "default": 1, "description": "Days to look ahead"},
        "max_results": {"type": "integer", "required": False, "default": 10},
    }
    OUTPUT_SCHEMA = {
        "success": {"type": "boolean"},
        "data": {"events": {"type": "array"}, "total": {"type": "integer"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "what's on my calendar today"}]
    SEMANTIC_TAGS = ["calendar", "events", "schedule", "meetings", "today"]
    TOOL_CATEGORY = "productivity"

    def get_tool_name(self) -> str:
        return "calendar_list_events"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            service = await _svc(inputs)
            days_ahead = int(inputs.get("days_ahead", 1))
            max_results = int(inputs.get("max_results", 10))

            now = datetime.utcnow()
            time_min = now.isoformat() + "Z"
            time_max = (now + timedelta(days=days_ahead)).isoformat() + "Z"

            resp = service.events().list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            ).execute()

            events = []
            for item in resp.get("items", []):
                start = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date", "")
                end = item.get("end", {}).get("dateTime") or item.get("end", {}).get("date", "")
                events.append({
                    "id": item["id"],
                    "summary": item.get("summary", "(no title)"),
                    "start": start,
                    "end": end,
                    "location": item.get("location", ""),
                    "description": item.get("description", ""),
                    "status": item.get("status", ""),
                })

            return ToolOutput(success=True, data={"events": events, "total": len(events)})
        except Exception as exc:
            logger.error("calendar_list_events error: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))


class CalendarCreateEventTool(BaseTool):
    """
    Create a new calendar event.

    Inputs:
    - user_id (string, required)
    - summary (string, required): Event title
    - start_time (string, required): ISO datetime e.g. "2026-05-25T10:00:00"
    - end_time (string, required): ISO datetime
    - description (string, optional)
    - location (string, optional)

    Outputs:
    - event_id (string)
    - summary (string)
    - link (string): Google Calendar event link
    """

    TOOL_DESCRIPTION = "Create a new calendar event with time, title, and optional details"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA = {
        "user_id": {"type": "string", "required": True},
        "summary": {"type": "string", "required": True, "description": "Event title"},
        "start_time": {"type": "string", "required": True, "description": "ISO datetime"},
        "end_time": {"type": "string", "required": True, "description": "ISO datetime"},
        "description": {"type": "string", "required": False, "default": ""},
        "location": {"type": "string", "required": False, "default": ""},
    }
    OUTPUT_SCHEMA = {
        "success": {"type": "boolean"},
        "data": {"event_id": {"type": "string"}, "summary": {"type": "string"}, "link": {"type": "string"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "schedule a meeting tomorrow at 2pm"}]
    SEMANTIC_TAGS = ["calendar", "create", "event", "schedule", "meeting"]
    TOOL_CATEGORY = "productivity"

    def get_tool_name(self) -> str:
        return "calendar_create_event"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            service = await _svc(inputs)

            event_body = {
                "summary": inputs["summary"],
                "start": {"dateTime": inputs["start_time"], "timeZone": "Asia/Kolkata"},
                "end": {"dateTime": inputs["end_time"], "timeZone": "Asia/Kolkata"},
            }
            if inputs.get("description"):
                event_body["description"] = inputs["description"]
            if inputs.get("location"):
                event_body["location"] = inputs["location"]

            event = service.events().insert(calendarId="primary", body=event_body).execute()

            return ToolOutput(success=True, data={
                "event_id": event["id"],
                "summary": event.get("summary", ""),
                "link": event.get("htmlLink", ""),
            })
        except Exception as exc:
            logger.error("calendar_create_event error: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))


__all__ = ["CalendarListEventsTool", "CalendarCreateEventTool"]
