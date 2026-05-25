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
    METADATA = {"summary_tts": True}
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


class CalendarUpdateEventTool(BaseTool):
    """
    Update an existing calendar event.

    Inputs:
    - user_id (string, required)
    - event_id (string, optional): Google event ID — preferred
    - summary_search (string, optional): Search by title if event_id not known
    - new_summary (string, optional): New event title
    - new_start_time (string, optional): New ISO datetime e.g. "2026-05-25T10:00:00"
    - new_end_time (string, optional): New ISO datetime
    - new_description (string, optional)
    - new_location (string, optional)

    Outputs:
    - event_id (string), summary (string), link (string)
    """

    TOOL_DESCRIPTION = "Update an existing calendar event — reschedule, rename, or edit details"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA = {
        "user_id": {"type": "string", "required": True},
        "event_id": {"type": "string", "required": False, "default": "", "description": "Google Calendar event ID"},
        "summary_search": {"type": "string", "required": False, "default": "", "description": "Search for event by title if ID not known"},
        "new_summary": {"type": "string", "required": False, "default": "", "description": "New event title"},
        "new_start_time": {"type": "string", "required": False, "default": "", "description": "New start datetime (ISO)"},
        "new_end_time": {"type": "string", "required": False, "default": "", "description": "New end datetime (ISO)"},
        "new_description": {"type": "string", "required": False, "default": ""},
        "new_location": {"type": "string", "required": False, "default": ""},
    }
    OUTPUT_SCHEMA = {
        "success": {"type": "boolean"},
        "data": {"event_id": {"type": "string"}, "summary": {"type": "string"}, "link": {"type": "string"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [
        {"user_utterance": "reschedule my 3pm meeting to 4pm"},
        {"user_utterance": "change the standup title to Weekly Sync"},
    ]
    SEMANTIC_TAGS = ["calendar", "update", "reschedule", "edit", "event", "meeting"]
    TOOL_CATEGORY = "productivity"

    def get_tool_name(self) -> str:
        return "calendar_update_event"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            service = await _svc(inputs)

            event_id = str(inputs.get("event_id", "")).strip()

            # Resolve event_id via title search if not provided
            if not event_id:
                search_term = str(inputs.get("summary_search", "")).strip()
                if not search_term:
                    return ToolOutput(success=False, data={}, error="Provide event_id or summary_search to identify the event.")
                now = datetime.utcnow()
                resp = service.events().list(
                    calendarId="primary",
                    q=search_term,
                    timeMin=now.isoformat() + "Z",
                    maxResults=5,
                    singleEvents=True,
                    orderBy="startTime",
                ).execute()
                items = resp.get("items", [])
                if not items:
                    return ToolOutput(success=False, data={}, error=f"No upcoming event found matching '{search_term}'.")
                event_id = items[0]["id"]

            # Fetch current event body
            event = service.events().get(calendarId="primary", eventId=event_id).execute()

            # Apply patches
            if inputs.get("new_summary"):
                event["summary"] = inputs["new_summary"]
            if inputs.get("new_description"):
                event["description"] = inputs["new_description"]
            if inputs.get("new_location"):
                event["location"] = inputs["new_location"]
            if inputs.get("new_start_time"):
                event["start"] = {"dateTime": inputs["new_start_time"], "timeZone": "Asia/Kolkata"}
            if inputs.get("new_end_time"):
                event["end"] = {"dateTime": inputs["new_end_time"], "timeZone": "Asia/Kolkata"}

            updated = service.events().update(
                calendarId="primary", eventId=event_id, body=event
            ).execute()

            return ToolOutput(success=True, data={
                "event_id": updated["id"],
                "summary": updated.get("summary", ""),
                "link": updated.get("htmlLink", ""),
            })
        except Exception as exc:
            logger.error("calendar_update_event error: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))


class CalendarDeleteEventTool(BaseTool):
    """
    Delete (cancel) a calendar event.

    Inputs:
    - user_id (string, required)
    - event_id (string, optional): Google event ID — preferred
    - summary_search (string, optional): Search by title if event_id not known

    Outputs:
    - event_id (string), summary (string), deleted (bool)
    """

    TOOL_DESCRIPTION = "Delete or cancel a calendar event"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA = {
        "user_id": {"type": "string", "required": True},
        "event_id": {"type": "string", "required": False, "default": "", "description": "Google Calendar event ID"},
        "summary_search": {"type": "string", "required": False, "default": "", "description": "Search for event by title if ID not known"},
    }
    OUTPUT_SCHEMA = {
        "success": {"type": "boolean"},
        "data": {"event_id": {"type": "string"}, "summary": {"type": "string"}, "deleted": {"type": "boolean"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [
        {"user_utterance": "cancel my standup meeting"},
        {"user_utterance": "delete tomorrow's dentist appointment"},
    ]
    SEMANTIC_TAGS = ["calendar", "delete", "cancel", "remove", "event", "meeting"]
    TOOL_CATEGORY = "productivity"

    def get_tool_name(self) -> str:
        return "calendar_delete_event"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            service = await _svc(inputs)

            event_id = str(inputs.get("event_id", "")).strip()
            resolved_summary = ""

            # Resolve event_id via title search if not provided
            if not event_id:
                search_term = str(inputs.get("summary_search", "")).strip()
                if not search_term:
                    return ToolOutput(success=False, data={}, error="Provide event_id or summary_search to identify the event.")
                now = datetime.utcnow()
                resp = service.events().list(
                    calendarId="primary",
                    q=search_term,
                    timeMin=now.isoformat() + "Z",
                    maxResults=5,
                    singleEvents=True,
                    orderBy="startTime",
                ).execute()
                items = resp.get("items", [])
                if not items:
                    return ToolOutput(success=False, data={}, error=f"No upcoming event found matching '{search_term}'.")
                event_id = items[0]["id"]
                resolved_summary = items[0].get("summary", "")

            if not resolved_summary:
                try:
                    ev = service.events().get(calendarId="primary", eventId=event_id).execute()
                    resolved_summary = ev.get("summary", "")
                except Exception:
                    pass

            service.events().delete(calendarId="primary", eventId=event_id).execute()

            return ToolOutput(success=True, data={
                "event_id": event_id,
                "summary": resolved_summary,
                "deleted": True,
            })
        except Exception as exc:
            logger.error("calendar_delete_event error: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))


class CalendarSearchEventsTool(BaseTool):
    """
    Search calendar events by keyword across a date range.

    Inputs:
    - user_id (string, required)
    - query (string, required): Search keyword (title, description, location)
    - days_back (integer, optional): How many past days to include (default: 0)
    - days_ahead (integer, optional): How many future days to include (default: 30)
    - max_results (integer, optional): Max events to return (default: 10)

    Outputs:
    - events (array), total (integer)
    """

    TOOL_DESCRIPTION = "Search for calendar events by keyword across a date range"
    EXECUTION_TARGET = "server"
    METADATA = {"summary_tts": True}
    PARAMS_SCHEMA = {
        "user_id": {"type": "string", "required": True},
        "query": {"type": "string", "required": True, "description": "Keyword to search (title, description, location)"},
        "days_back": {"type": "integer", "required": False, "default": 0, "description": "Past days to search"},
        "days_ahead": {"type": "integer", "required": False, "default": 30, "description": "Future days to search"},
        "max_results": {"type": "integer", "required": False, "default": 10},
    }
    OUTPUT_SCHEMA = {
        "success": {"type": "boolean"},
        "data": {"events": {"type": "array"}, "total": {"type": "integer"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [
        {"user_utterance": "find my dentist appointment"},
        {"user_utterance": "search calendar for team meeting"},
    ]
    SEMANTIC_TAGS = ["calendar", "search", "find", "events", "meeting", "appointment"]
    TOOL_CATEGORY = "productivity"

    def get_tool_name(self) -> str:
        return "calendar_search_events"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            service = await _svc(inputs)
            query = str(inputs.get("query", "")).strip()
            if not query:
                return ToolOutput(success=False, data={}, error="query is required")

            days_back = int(inputs.get("days_back", 0))
            days_ahead = int(inputs.get("days_ahead", 30))
            max_results = int(inputs.get("max_results", 10))

            now = datetime.utcnow()
            time_min = (now - timedelta(days=days_back)).isoformat() + "Z"
            time_max = (now + timedelta(days=days_ahead)).isoformat() + "Z"

            resp = service.events().list(
                calendarId="primary",
                q=query,
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
                })

            return ToolOutput(success=True, data={"events": events, "total": len(events)})
        except Exception as exc:
            logger.error("calendar_search_events error: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))


__all__ = [
    "CalendarListEventsTool",
    "CalendarCreateEventTool",
    "CalendarUpdateEventTool",
    "CalendarDeleteEventTool",
    "CalendarSearchEventsTool",
]
