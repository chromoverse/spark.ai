"""
Test: organize_day progress events and output structure.

Verifies:
  - Progress events are emitted in the correct order
  - Each stage has the right stage/message
  - Output data structure is correct
  - _build_result_summary produces the expected one-liner
  - Edge cases: no services connected, single service, all services
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# ── Import gate ──────────────────────────────────────────────────────────────

try:
    from plugins.installed.spark.tools.organize_day import OrganizeDayTool
    _IMPORT_ERROR = None
except Exception as exc:
    OrganizeDayTool = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc

# _build_result_summary lives in execution_engine.py — import directly
try:
    from app.kernel.execution.execution_engine import _build_result_summary
    _SUMMARY_IMPORT_ERROR = None
except Exception as exc:
    _build_result_summary = None  # type: ignore[assignment]
    _SUMMARY_IMPORT_ERROR = exc


# ── Mock helpers ─────────────────────────────────────────────────────────────

def _mock_gmail_service(messages_count: int = 3):
    """Return a MagicMock chain that mimics the Gmail API builder pattern."""
    svc = MagicMock()

    # Each message will return a detail with From/Subject/Date headers
    def _get_message_detail(**__):
        detail = MagicMock()
        detail.execute.return_value = {
            "payload": {
                "headers": [
                    {"name": "From", "value": "alice@example.com"},
                    {"name": "Subject", "value": "Meeting reminder"},
                    {"name": "Date", "value": "2026-05-25T09:00:00Z"},
                ],
            },
        }
        return detail

    # List response
    msg_ids = [{"id": f"msg{i}"} for i in range(messages_count)]
    svc.users().messages().list().execute.return_value = {
        "messages": msg_ids,
        "resultSizeEstimate": messages_count,
    }
    # Each get() call returns a detail with the headers
    svc.users().messages().get.side_effect = _get_message_detail

    return svc


def _mock_calendar_service(event_count: int = 2):
    """Return a MagicMock chain that mimics the Calendar API builder pattern."""
    svc = MagicMock()

    events = []
    for i in range(event_count):
        ev = {
            "summary": f"Event {i + 1}",
            "start": {"dateTime": f"2026-05-25T0{i + 9}:00:00"},
            "location": f"Room {i + 1}" if i == 0 else "",
            "attendees": [{"email": "a@b.com"}] * (i + 1),
        }
        events.append(ev)

    svc.events().list().execute.return_value = {"items": events}
    return svc


# ── Tests ────────────────────────────────────────────────────────────────────


@unittest.skipIf(_IMPORT_ERROR is not None, f"OrganizeDayTool imports unavailable: {_IMPORT_ERROR}")
class OrganizeDayProgressTests(unittest.TestCase):
    """Verify progress event emission and output structure."""

    maxDiff = None

    # ── All three services connected ──────────────────────────────────────

    def test_all_three_services_emits_progress_in_correct_order(self):
        """With Gmail + Calendar + Slack, progress events flow: checking → 3x fetching → gathering → complete."""
        captured: list[dict] = []

        async def _capture_emit(user_id, event_type, **kwargs):
            captured.append({
                "user_id": user_id,
                "event_type": event_type,
                **kwargs,
            })

        async def _run():
            tool = OrganizeDayTool()

            mock_statuses = [
                {"id": "gmail", "connected": True},
                {"id": "google_calendar", "connected": True},
                {"id": "slack", "connected": True},
                {"id": "notion", "connected": False},
                {"id": "github", "connected": False},
            ]

            with (
                patch("plugins.installed.spark.tools.organize_day.get_all_connector_statuses",
                      AsyncMock(return_value=mock_statuses)),
                patch("app.connectors.clients.gmail.get_gmail_service",
                      AsyncMock(return_value=_mock_gmail_service(3))),
                patch("app.connectors.clients.calendar.get_calendar_service",
                      AsyncMock(return_value=_mock_calendar_service(2))),
                patch("app.socket.log_stream.emit_spark_log",
                      side_effect=_capture_emit),
            ):
                result = await tool._execute({
                    "_user_id": "test_user",
                    "_task_id": "step_1",
                })

            return result

        result = asyncio.run(_run())

        # ── Assert success ──
        self.assertTrue(result.success, f"Tool should succeed, got error: {result.error}")
        self.assertIsNone(result.error)

        # ── Assert output structure ──
        data = result.data or {}
        self.assertIn("summary", data)
        s = data["summary"]
        self.assertIn("email", s)
        self.assertIn("calendar", s)
        self.assertIn("slack", s)
        self.assertIn("connected_services", s)
        self.assertEqual(s["connected_services"], ["gmail", "google_calendar", "slack"])
        self.assertEqual(s["service_count"], 3)

        # Email data
        self.assertEqual(s["email"]["unread_count"], 3)
        self.assertTrue(s["email"]["has_unread"])
        self.assertEqual(len(s["email"]["preview"]), 3)

        # Calendar data
        self.assertEqual(s["calendar"]["event_count"], 2)
        self.assertEqual(len(s["calendar"]["events"]), 2)
        self.assertTrue(s["calendar"]["has_events"])

        # Slack data
        self.assertTrue(s["slack"]["connected"])

        # ── Assert progress event order ──
        # Filter only tool_progress events
        progress_events = [e for e in captured if e["event_type"] == "tool_progress"]
        self.assertGreaterEqual(len(progress_events), 5,
                                "Should have at least 5 progress events "
                                "(checking + 3 fetching + gathering + complete)")

        stages = [e["payload"]["stage"] for e in progress_events]
        messages = [e["payload"]["message"] for e in progress_events]

        self.assertEqual(stages[0], "checking")
        self.assertIn("3 connected", messages[0])

        # Next 3 should be fetching (one per service)
        self.assertEqual(stages[1], "fetching")
        self.assertIn("emails", messages[1].lower())

        self.assertEqual(stages[2], "fetching")
        self.assertIn("calendar", messages[2].lower())

        self.assertEqual(stages[3], "fetching")
        self.assertIn("slack", messages[3].lower())

        # Then gathering
        gathering_idx = next(i for i, s in enumerate(stages) if s == "gathering")
        self.assertIn("3 service(s)", messages[gathering_idx])

        # Finally complete
        self.assertEqual(stages[-1], "complete")
        self.assertIn("3 service", messages[-1])

        # ── Assert task_id and tool_name in every event ──
        for evt in progress_events:
            self.assertEqual(evt.get("task_id"), "step_1",
                             f"All progress events should carry task_id=step_1: {evt}")
            self.assertEqual(evt.get("tool_name"), "organize_day",
                             f"All progress events should carry tool_name=organize_day: {evt}")

    # ── Only Gmail connected ──────────────────────────────────────────────

    def test_only_gmail_connected(self):
        """With only Gmail connected, only email progress and data appear."""
        captured: list[dict] = []

        async def _capture(user_id, event_type, **kwargs):
            captured.append({"event_type": event_type, "payload": kwargs.get("payload", {})})

        async def _run():
            tool = OrganizeDayTool()
            mock_statuses = [
                {"id": "gmail", "connected": True},
                {"id": "google_calendar", "connected": False},
                {"id": "slack", "connected": False},
                {"id": "notion", "connected": False},
                {"id": "github", "connected": False},
            ]

            with (
                patch("plugins.installed.spark.tools.organize_day.get_all_connector_statuses",
                      AsyncMock(return_value=mock_statuses)),
                patch("app.connectors.clients.gmail.get_gmail_service",
                      AsyncMock(return_value=_mock_gmail_service(1))),
                patch("app.socket.log_stream.emit_spark_log", side_effect=_capture),
            ):
                result = await tool._execute({
                    "_user_id": "test_user",
                    "_task_id": "step_1",
                })

            return result

        result = asyncio.run(_run())
        self.assertTrue(result.success)

        s = result.data["summary"]
        self.assertIn("email", s)
        self.assertNotIn("calendar", s)  # not fetched
        self.assertNotIn("slack", s)      # not fetched
        self.assertEqual(s["service_count"], 1)
        self.assertEqual(s["connected_services"], ["gmail"])

        # Only one service → only one fetching event
        fetch_msgs = [
            e["payload"].get("message", "")
            for e in captured
            if e["event_type"] == "tool_progress" and e["payload"].get("stage") == "fetching"
        ]
        self.assertEqual(len(fetch_msgs), 1)
        self.assertIn("email", fetch_msgs[0].lower())

    # ── No services connected ─────────────────────────────────────────────

    def test_no_services_connected_returns_empty_summary(self):
        """With zero connected services, no fetching happens and the summary is minimal."""
        captured: list[dict] = []

        async def _capture(user_id, event_type, **kwargs):
            captured.append({"event_type": event_type, "payload": kwargs.get("payload", {})})

        async def _run():
            tool = OrganizeDayTool()
            mock_statuses = [
                {"id": "gmail", "connected": False},
                {"id": "google_calendar", "connected": False},
                {"id": "slack", "connected": False},
                {"id": "notion", "connected": False},
                {"id": "github", "connected": False},
            ]

            with (
                patch("plugins.installed.spark.tools.organize_day.get_all_connector_statuses",
                      AsyncMock(return_value=mock_statuses)),
                patch("app.socket.log_stream.emit_spark_log", side_effect=_capture),
            ):
                result = await tool._execute({
                    "_user_id": "test_user",
                    "_task_id": "step_1",
                })

            return result

        result = asyncio.run(_run())
        self.assertTrue(result.success)

        s = result.data["summary"]
        self.assertNotIn("email", s)
        self.assertNotIn("calendar", s)
        self.assertNotIn("slack", s)
        self.assertEqual(s["service_count"], 0)
        self.assertEqual(s["connected_services"], [])

        # Only checking + complete — no fetching
        stages = [
            e["payload"].get("stage", "")
            for e in captured
            if e["event_type"] == "tool_progress"
        ]
        self.assertIn("checking", stages)
        self.assertIn("complete", stages)
        self.assertNotIn("fetching", stages)
        # Gathering fires even with 0 tasks (before the gather() call)
        self.assertIn("gathering", stages)

    # ── Service fetch failure handling ────────────────────────────────────

    def test_service_fetch_failure_records_error_in_summary(self):
        """If Gmail fails, the summary should record an error for that key."""
        async def _run():
            tool = OrganizeDayTool()
            mock_statuses = [
                {"id": "gmail", "connected": True},
                {"id": "google_calendar", "connected": False},
                {"id": "slack", "connected": False},
                {"id": "notion", "connected": False},
                {"id": "github", "connected": False},
            ]

            with (
                patch("plugins.installed.spark.tools.organize_day.get_all_connector_statuses",
                      AsyncMock(return_value=mock_statuses)),
                patch("app.connectors.clients.gmail.get_gmail_service",
                      AsyncMock(side_effect=RuntimeError("Token expired"))),
                patch("app.socket.log_stream.emit_spark_log"),
            ):
                result = await tool._execute({
                    "_user_id": "test_user",
                    "_task_id": "step_1",
                })
                return result

        result = asyncio.run(_run())
        self.assertTrue(result.success)

        s = result.data["summary"]
        self.assertIn("email", s)
        self.assertIn("error", s["email"])
        self.assertIn("Token expired", s["email"]["error"])

    # ── _build_result_summary integration ─────────────────────────────────

    @unittest.skipIf(_SUMMARY_IMPORT_ERROR is not None,
                     f"_build_result_summary unavailable: {_SUMMARY_IMPORT_ERROR}")
    def test_build_result_summary_with_full_output(self):
        """_build_result_summary produces a readable one-liner from organize_day output."""
        output_data = {
            "summary": {
                "email": {"unread_count": 3, "has_unread": True},
                "calendar": {"event_count": 5, "has_events": True},
                "slack": {"connected": True},
                "connected_services": ["gmail", "google_calendar", "slack"],
                "service_count": 3,
            },
        }
        summary = _build_result_summary("organize_day", output_data)
        self.assertIn("3 unread", summary)
        self.assertIn("5 events", summary)
        self.assertIn("Slack: connected", summary)

    @unittest.skipIf(_SUMMARY_IMPORT_ERROR is not None,
                     f"_build_result_summary unavailable: {_SUMMARY_IMPORT_ERROR}")
    def test_build_result_summary_partial_services(self):
        """Summary correctly reflects only the services present."""
        output_data = {
            "summary": {
                "email": {"unread_count": 1, "has_unread": True},
                "connected_services": ["gmail"],
                "service_count": 1,
            },
        }
        summary = _build_result_summary("organize_day", output_data)
        self.assertIn("1 unread", summary)
        self.assertNotIn("Calendar", summary)
        self.assertNotIn("Slack", summary)

    @unittest.skipIf(_SUMMARY_IMPORT_ERROR is not None,
                     f"_build_result_summary unavailable: {_SUMMARY_IMPORT_ERROR}")
    def test_build_result_summary_empty_data_returns_empty_string(self):
        """Empty data produces empty summary string."""
        self.assertEqual(_build_result_summary("organize_day", {}), "")

    # ── Ensure _execute rejects missing user_id ───────────────────────────

    def test_missing_user_id_returns_error(self):
        """Calling _execute without user_id should fail gracefully."""
        async def _run():
            tool = OrganizeDayTool()
            with patch("app.socket.log_stream.emit_spark_log"):
                result = await tool._execute({})
                return result

        result = asyncio.run(_run())
        self.assertFalse(result.success)
        self.assertIn("user_id", (result.error or "").lower())


if __name__ == "__main__":
    unittest.main()
