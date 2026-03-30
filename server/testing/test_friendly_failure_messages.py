import unittest

try:
    from app.kernel.execution.orchestrator import TaskOrchestrator
    from app.kernel.execution.failure_messages import (
        build_failure_detail,
        normalize_failure,
    )
    from app.services.chat.task_summary_speech_service import (
        ExecutionSpeechSnapshot,
        _fallback,
        _render_preview,
    )
    _IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - environment-dependent import gate
    TaskOrchestrator = None  # type: ignore[assignment]
    build_failure_detail = None  # type: ignore[assignment]
    normalize_failure = None  # type: ignore[assignment]
    ExecutionSpeechSnapshot = None  # type: ignore[assignment]
    _fallback = None  # type: ignore[assignment]
    _render_preview = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc


@unittest.skipIf(_IMPORT_ERROR is not None, f"Friendly failure imports unavailable: {_IMPORT_ERROR}")
class FriendlyFailureMessageTests(unittest.TestCase):
    def test_validation_error_is_normalized_for_users(self):
        raw_error = "Input validation failed: Parameter 'days' must be integer, got str"

        normalized = normalize_failure("weather_forecast", raw_error)

        self.assertEqual(normalized["raw_error"], raw_error)
        self.assertEqual(
            normalized["user_message"],
            "I couldn't get the forecast because the number of days was sent in the wrong format.",
        )

    def test_failure_detail_uses_public_keys(self):
        detail = build_failure_detail(
            task_id="step_1",
            tool_name="weather_forecast",
            raw_error="Input validation failed: Parameter 'days' must be integer, got str",
        )

        self.assertEqual(detail["taskId"], "step_1")
        self.assertEqual(detail["tool"], "weather_forecast")
        self.assertIn("rawError", detail)
        self.assertIn("userMessage", detail)

    def test_http_400_weather_failure_is_normalized_for_users(self):
        raw_error = "Weather service rejected the request: Latitude must be in range of -90 to 90"

        normalized = normalize_failure("weather_current", raw_error)

        self.assertEqual(normalized["raw_error"], raw_error)
        self.assertEqual(
            normalized["user_message"],
            "I couldn't get the weather because the weather service rejected the request: Latitude must be in range of -90 to 90.",
        )

    def test_invalid_weather_coordinates_are_normalized_for_users(self):
        raw_error = "Latitude and longitude must be valid numbers."

        normalized = normalize_failure("weather_current", raw_error)

        self.assertEqual(
            normalized["user_message"],
            "I couldn't get the weather because the location was sent in the wrong format.",
        )

    def test_summary_fallback_prefers_friendly_failure_message(self):
        snapshot = ExecutionSpeechSnapshot(
            user_id="u1",
            summary={
                "total": 1,
                "pending": 0,
                "running": 0,
                "completed": 0,
                "failed": 1,
                "waiting": 0,
                "skipped": 0,
                "emitted": 0,
                "failures": [],
            },
            tasks=[
                {
                    "task_id": "step_1",
                    "tool": "weather_forecast",
                    "status": "failed",
                    "raw_error": "Input validation failed: Parameter 'days' must be integer, got str",
                    "user_message": "I couldn't get the forecast because the number of days was sent in the wrong format.",
                    "output_preview": {},
                }
            ],
            has_state=True,
        )

        text = _fallback(snapshot, ack_hint="", user_lang="en", lang_label="English")

        self.assertEqual(
            text,
            "I couldn't get the forecast because the number of days was sent in the wrong format.",
        )

    def test_summary_fallback_keeps_partial_success_brief(self):
        snapshot = ExecutionSpeechSnapshot(
            user_id="u1",
            summary={
                "total": 2,
                "pending": 0,
                "running": 0,
                "completed": 1,
                "failed": 1,
                "waiting": 0,
                "skipped": 0,
                "emitted": 0,
                "failures": [],
            },
            tasks=[
                {
                    "task_id": "step_1",
                    "tool": "weather_current",
                    "status": "completed",
                    "output_preview": {"target": "Weather"},
                },
                {
                    "task_id": "step_2",
                    "tool": "weather_forecast",
                    "status": "failed",
                    "raw_error": "Input validation failed: Parameter 'days' must be integer, got str",
                    "user_message": "I couldn't get the forecast because the number of days was sent in the wrong format.",
                    "output_preview": {},
                },
            ],
            has_state=True,
        )

        text = _fallback(snapshot, ack_hint="", user_lang="en", lang_label="English")

        self.assertEqual(
            text,
            "Most of it worked, but I couldn't get the forecast because the number of days was sent in the wrong format.",
        )

    def test_render_preview_uses_actual_structured_values(self):
        rendered = _render_preview(
            {
                "location": "Kathmandu, Nepal",
                "days_returned": 5,
                "forecast": [
                    {
                        "date": "2026-03-31",
                        "condition": "Partly cloudy",
                        "temp_max": "22°C",
                        "temp_min": "12°C",
                    }
                ],
            }
        )

        self.assertIn("location Kathmandu, Nepal", rendered)
        self.assertIn("forecast date 2026-03-31", rendered)
        self.assertIn("forecast condition Partly cloudy", rendered)

    def test_success_fallback_speaks_output_values_not_generic_done(self):
        snapshot = ExecutionSpeechSnapshot(
            user_id="u1",
            summary={
                "total": 1,
                "pending": 0,
                "running": 0,
                "completed": 1,
                "failed": 0,
                "waiting": 0,
                "skipped": 0,
                "emitted": 0,
                "failures": [],
            },
            tasks=[
                {
                    "task_id": "step_1",
                    "tool": "weather_forecast",
                    "status": "completed",
                    "output_preview": {
                        "location": "Kathmandu, Nepal",
                        "days_returned": 5,
                        "forecast": [
                            {
                                "date": "2026-03-31",
                                "condition": "Partly cloudy",
                                "temp_max": "22°C",
                                "temp_min": "12°C",
                            }
                        ],
                    },
                }
            ],
            has_state=True,
        )

        text = _fallback(snapshot, ack_hint="", user_lang="en", lang_label="English")

        self.assertIn("Kathmandu, Nepal", text)
        self.assertIn("2026-03-31", text)
        self.assertNotEqual(text, "Done. That's taken care of.")

    def test_compact_summary_keeps_useful_top_level_long_text(self):
        orchestrator = TaskOrchestrator()
        formatted_content = " ".join(["This is a detailed answer."] * 20)

        compacted = orchestrator._compact_summary_value(
            {
                "summary": "Short answer.",
                "formatted_content": formatted_content,
            }
        )

        self.assertEqual(compacted["formatted_content"], formatted_content)


if __name__ == "__main__":
    unittest.main()
