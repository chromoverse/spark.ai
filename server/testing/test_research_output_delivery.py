import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

try:
    from app.kernel.execution.execution_models import ExecutionState, Task, TaskOutput, TaskRecord
    from app.services.chat.tool_output_delivery_service import ToolOutputDeliveryService
    from tools.tools.base import ToolOutput
    from tools.tools.web.research import WebResearchTool
    _IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - environment-dependent import gate
    ExecutionState = None  # type: ignore[assignment]
    Task = None  # type: ignore[assignment]
    TaskOutput = None  # type: ignore[assignment]
    TaskRecord = None  # type: ignore[assignment]
    ToolOutput = None  # type: ignore[assignment]
    ToolOutputDeliveryService = None  # type: ignore[assignment]
    WebResearchTool = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc


@unittest.skipIf(_IMPORT_ERROR is not None, f"Research output imports unavailable: {_IMPORT_ERROR}")
class ResearchOutputDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_web_research_passes_mode_to_summarizer_and_returns_detailed_content(self):
        fake_search = SimpleNamespace(
            execute=AsyncMock(
                return_value=ToolOutput(
                    success=True,
                    data={"results": [{"url": "https://example.com"}]},
                    error=None,
                )
            )
        )
        fake_scrape = SimpleNamespace(
            _execute=AsyncMock(
                return_value=ToolOutput(
                    success=True,
                    data={
                        "results": [
                            {
                                "success": True,
                                "url": "https://example.com",
                                "title": "Example",
                                "text": "Useful source content.",
                            }
                        ]
                    },
                    error=None,
                )
            )
        )
        fake_summarize = SimpleNamespace(
            execute=AsyncMock(
                return_value=ToolOutput(
                    success=True,
                    data={
                        "summary": "Short answer.",
                        "formatted_content": "Long detailed answer.",
                    },
                    error=None,
                )
            )
        )

        with (
            patch("tools.tools.web.research.WebSearchTool", return_value=fake_search),
            patch("tools.tools.web.research.WebScrapeTool", return_value=fake_scrape),
            patch("tools.tools.web.research.AiSummarizeTool", return_value=fake_summarize),
        ):
            result = await WebResearchTool()._execute(
                {
                    "query": "Explain the example.",
                    "mode": "research",
                    "max_results": 1,
                }
            )

        self.assertTrue(result.success)
        self.assertEqual(result.data["summary"], "Short answer.")
        self.assertEqual(result.data["detailed_content"], "Long detailed answer.")
        summarize_inputs = fake_summarize.execute.await_args.args[0]
        self.assertEqual(summarize_inputs["mode"], "research")

    async def test_web_research_output_delivery_includes_detailed_content_by_default(self):
        state = ExecutionState(user_id="u1")
        state.add_task(
            TaskRecord(
                task=Task(
                    task_id="step_1",
                    tool="web_research",
                    execution_target="server",
                ),
                status="completed",
                output=TaskOutput(
                    success=True,
                    data={
                        "query": "example query",
                        "summary": "Short answer.",
                        "detailed_content": "Long detailed answer.",
                        "sources": [],
                    },
                ),
            )
        )
        fake_orchestrator = SimpleNamespace(get_state=lambda user_id: state)

        with patch(
            "app.services.chat.tool_output_delivery_service.get_orchestrator",
            return_value=fake_orchestrator,
        ):
            payload = await ToolOutputDeliveryService().get_output(
                user_id="u1",
                tool_name="web_research",
            )

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertIn("detailed_content", payload["data"])
        self.assertEqual(payload["data"]["detailed_content"], "Long detailed answer.")

    async def test_ai_summarize_output_delivery_includes_formatted_content_by_default(self):
        state = ExecutionState(user_id="u1")
        state.add_task(
            TaskRecord(
                task=Task(
                    task_id="step_1",
                    tool="ai_summarize",
                    execution_target="server",
                ),
                status="completed",
                output=TaskOutput(
                    success=True,
                    data={
                        "summary": "Short answer.",
                        "formatted_content": "Long formatted answer.",
                        "original_length": 120,
                        "summary_length": 14,
                        "summarized_at": "2026-03-30T00:00:00+00:00",
                    },
                ),
            )
        )
        fake_orchestrator = SimpleNamespace(get_state=lambda user_id: state)

        with patch(
            "app.services.chat.tool_output_delivery_service.get_orchestrator",
            return_value=fake_orchestrator,
        ):
            payload = await ToolOutputDeliveryService().get_output(
                user_id="u1",
                tool_name="ai_summarize",
            )

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertIn("formatted_content", payload["data"])
        self.assertEqual(payload["data"]["formatted_content"], "Long formatted answer.")


if __name__ == "__main__":
    unittest.main()
