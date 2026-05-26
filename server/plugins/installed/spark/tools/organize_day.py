"""'Organize my day' — aggregate data from all connected services."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.connectors.registry import get_all_connector_statuses
from app.plugins.tools.tool_base import BaseTool, ToolOutput

logger = logging.getLogger(__name__)


async def _emit_progress(user_id: str, task_id: str, stage: str, message: str) -> None:
    """Emit a tool_progress event so the UI shows each step in real-time."""
    if not user_id:
        return
    try:
        from app.socket.log_stream import emit_spark_log
        await emit_spark_log(
            user_id,
            "tool_progress",
            task_id=task_id,
            tool_name="organize_day",
            payload={"stage": stage, "message": message},
        )
    except Exception:
        pass


async def _emit_service_output(
    user_id: str, task_id: str, service: str, data: dict, summary_line: str
) -> None:
    """Emit a tool_progress event with rich service output data for the UI."""
    if not user_id:
        return
    try:
        from app.socket.log_stream import emit_spark_log
        await emit_spark_log(
            user_id,
            "tool_progress",
            task_id=task_id,
            tool_name="organize_day",
            payload={
                "stage": "service_output",
                "service": service,
                "data": data,
                "message": summary_line,
            },
        )
    except Exception:
        pass


async def _run_summarize(context: str) -> str:
    """Call the ai_summarize internals to produce a natural language summary."""
    if not context.strip():
        return ""
    try:
        from app.ai.providers.router import routed_chat
        timestamp = datetime.now(timezone.utc).isoformat()
        prompt = f"""You are a personal assistant. Summarize the user's current day status in 2-3 natural, warm sentences.
Talk about what's happening — emails to check, upcoming events, and any general vibe for the day.
Be concise and conversational. Always respond in English.

CONTEXT:
{context}

OUTPUT (plain text, no JSON, no markdown):"""
        response, _ = await routed_chat(
            "summarize",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=400,
        )
        return (response or "").strip()
    except Exception as exc:
        logger.warning("organize_day summarization failed: %s", exc)
        return ""


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
        "data": {
            "summary": {"type": "object"},
            "narrative_summary": {"type": "string"},
            "suggested_followups": {"type": "array"},
        },
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
        task_id = str(inputs.get("_task_id") or "")
        if not user_id:
            return ToolOutput(success=False, data={}, error="user_id required")

        # Check what's connected
        statuses = await get_all_connector_statuses(user_id)
        connected = {s["id"] for s in statuses if s["connected"]}

        await _emit_progress(user_id, task_id, "checking", f"Found {len(connected)} connected services")

        summary: Dict[str, Any] = {}
        tasks: List[asyncio.Task] = []
        task_keys: List[str] = []

        # Fan out to connected services in parallel
        if "gmail" in connected:
            await _emit_progress(user_id, task_id, "fetching", "Fetching unread emails...")
            tasks.append(asyncio.create_task(self._get_emails(user_id)))
            task_keys.append("email")
        if "google_calendar" in connected:
            await _emit_progress(user_id, task_id, "fetching", "Fetching today's calendar events...")
            tasks.append(asyncio.create_task(self._get_calendar(user_id)))
            task_keys.append("calendar")
        if "slack" in connected:
            await _emit_progress(user_id, task_id, "fetching", "Checking Slack status...")
            tasks.append(asyncio.create_task(self._get_slack(user_id)))
            task_keys.append("slack")

        await _emit_progress(user_id, task_id, "gathering", f"Gathering data from {len(tasks)} service(s)...")
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for key, result in zip(task_keys, results):
            if not isinstance(result, Exception):
                summary[key] = result
            else:
                logger.warning("organize_day: %s fetch failed: %s", key, result)
                summary[key] = {"error": str(result)}

        summary["connected_services"] = sorted(connected)
        summary["service_count"] = len(connected)

        # Emit rich output per service so the UI shows individual results
        email_data = summary.get("email", {})
        cal_data = summary.get("calendar", {})
        slack_data = summary.get("slack", {})

        if email_data and not email_data.get("error"):
            unread = email_data.get("unread_count", 0)
            previews = email_data.get("preview", [])[:3]
            preview_lines = "\n".join(
                f"  · {p.get('from','?').split('<')[0].strip()}: {p.get('subject','(no subject)')[:60]}"
                for p in previews
            )
            await _emit_service_output(
                user_id, task_id, "email",
                data={"unread_count": unread, "previews": previews},
                summary_line=f"{unread} unread email{'s' if unread != 1 else ''}",
            )
            await _emit_progress(user_id, task_id, "service_detail",
                f"✉ {unread} unread\n{preview_lines}" if preview_lines else f"✉ {unread} unread")

        if cal_data and not cal_data.get("error"):
            count = cal_data.get("event_count", 0)
            events = cal_data.get("events", [])[:5]
            event_lines = "\n".join(
                f"  · {e.get('start','')[-8:-3] if len(e.get('start','')) > 10 else e.get('start','')} — {e.get('summary','(no title)')[:50]}"
                for e in events
            )
            await _emit_service_output(
                user_id, task_id, "calendar",
                data={"event_count": count, "events": events},
                summary_line=f"{count} event{'s' if count != 1 else ''} today",
            )
            await _emit_progress(user_id, task_id, "service_detail",
                f"📅 {count} today\n{event_lines}" if event_lines else f"📅 {count} today")

        if slack_data and not slack_data.get("error"):
            await _emit_service_output(
                user_id, task_id, "slack",
                data=slack_data,
                summary_line="Slack: connected",
            )
            await _emit_progress(user_id, task_id, "service_detail", "💬 Slack connected")

        # Build a text blob for AI summarization
        context_parts = []
        if email_data and not email_data.get("error"):
            unread = email_data.get("unread_count", 0)
            previews = email_data.get("preview", [])
            context_parts.append(f"Emails: {unread} unread")
            for p in previews[:3]:
                context_parts.append(f"  - From {p.get('from','?')}: {p.get('subject','(no subject)')}")
        if cal_data and not cal_data.get("error"):
            count = cal_data.get("event_count", 0)
            events = cal_data.get("events", [])
            context_parts.append(f"Calendar: {count} events today")
            for e in events[:5]:
                start = e.get("start", "")[-8:-3] if len(e.get("start", "")) > 10 else e.get("start", "")
                context_parts.append(f"  - {start} — {e.get('summary','(no title)')}")
        if slack_data and not slack_data.get("error"):
            context_parts.append("Slack: connected")

        context_blob = "\n".join(context_parts)

        await _emit_progress(user_id, task_id, "summarizing", "Generating day summary...")
        narrative_summary = await _run_summarize(context_blob)

        # Auto-generate suggested follow-up tasks
        suggested_followups = []
        if email_data and not email_data.get("error") and email_data.get("unread_count", 0) > 0:
            suggested_followups.append({"type": "email", "text": f"Check {email_data['unread_count']} unread emails", "priority": "high"})
        if cal_data and not cal_data.get("error") and cal_data.get("event_count", 0) > 0:
            next_event = (cal_data.get("events") or [{}])[0].get("summary", "")
            if next_event:
                suggested_followups.append({"type": "calendar", "text": f"Prepare for '{next_event}'", "priority": "medium"})
        if slack_data and slack_data.get("connected"):
            suggested_followups.append({"type": "slack", "text": "Catch up on Slack messages", "priority": "low"})

        await _emit_progress(user_id, task_id, "complete", f"Done — collected data from {len(connected)} services")

        return ToolOutput(
            success=True, data={
                "summary": summary,
                "narrative_summary": narrative_summary,
                "suggested_followups": suggested_followups,
            }
        )

    async def _get_emails(self, user_id: str) -> dict:
        from app.connectors.clients.gmail import get_gmail_service
        service = await get_gmail_service(user_id)
        
        # Get unread emails with more details
        resp = service.users().messages().list(
            userId="me", labelIds=["INBOX", "UNREAD"], maxResults=10
        ).execute()
        
        messages = resp.get("messages", [])
        count = resp.get("resultSizeEstimate", 0)
        
        # Fetch details for preview messages
        previews = []
        for msg in messages[:3]:
            try:
                detail = service.users().messages().get(
                    userId="me", id=msg["id"], format="metadata",
                    metadataHeaders=["From", "Subject", "Date"]
                ).execute()
                headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
                previews.append({
                    "from": headers.get("From", "Unknown"),
                    "subject": headers.get("Subject", "(no subject)"),
                    "date": headers.get("Date", ""),
                })
            except Exception:
                pass
        
        return {
            "unread_count": count,
            "preview": previews,
            "has_unread": count > 0,
        }

    async def _get_calendar(self, user_id: str) -> dict:
        from app.connectors.clients.calendar import get_calendar_service
        from datetime import datetime, timedelta
        service = await get_calendar_service(user_id)
        now = datetime.utcnow()
        
        # Get today's events
        resp = service.events().list(
            calendarId="primary",
            timeMin=now.isoformat() + "Z",
            timeMax=(now + timedelta(days=1)).isoformat() + "Z",
            maxResults=20, singleEvents=True, orderBy="startTime",
        ).execute()
        
        events = []
        for e in resp.get("items", []):
            start = e.get("start", {})
            start_time = start.get("dateTime", start.get("date", ""))
            events.append({
                "summary": e.get("summary", "(no title)"),
                "start": start_time,
                "location": e.get("location", ""),
                "attendees": len(e.get("attendees", [])),
            })
        
        # Categorize events
        upcoming_soon = [e for e in events[:3]]  # Next 3 events
        total_today = len(events)
        
        return {
            "event_count": total_today,
            "events": events,
            "upcoming_soon": upcoming_soon,
            "has_events": total_today > 0,
        }

    async def _get_slack(self, user_id: str) -> dict:
        # Return connected status — detailed fetch requires channel selection
        return {
            "connected": True,
            "note": "Slack connected — ask about specific channels for messages",
        }


__all__ = ["OrganizeDayTool"]
