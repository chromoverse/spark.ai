import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

try:
    from tools.tools.system.app import AppOpenTool
    _IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - import gate
    AppOpenTool = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc


@unittest.skipIf(_IMPORT_ERROR is not None, f"AppOpenTool imports unavailable: {_IMPORT_ERROR}")
class AppOpenIntentFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_browser_destination_bypasses_local_app_search(self):
        tool = AppOpenTool()

        with (
            patch.object(tool.searcher, "search_local_app") as search_local_app,
            patch.object(
                tool.searcher,
                "resolve_website",
                return_value={"name": "GitHub", "path": "https://github.com", "type": "website"},
            ),
            patch.object(tool, "_validate_website_result", AsyncMock(return_value="https://github.com")),
            patch("tools.tools.system.app.webbrowser.open") as open_browser,
        ):
            result = await tool.execute({"target": "GitHub", "destination": "browser"})

        self.assertTrue(result.success)
        self.assertEqual(result.data["status"], "opened_in_browser")
        self.assertEqual(result.data["resolved_path"], "https://github.com")
        search_local_app.assert_not_called()
        open_browser.assert_called_once_with("https://github.com")

    async def test_auto_destination_prefers_local_app_over_web(self):
        tool = AppOpenTool()
        local_result = {
            "name": "GitHub Desktop",
            "path": "C:/Program Files/GitHub Desktop/GitHubDesktop.exe",
            "type": "exe",
            "launch_method": "run",
            "source": "cache",
        }
        fake_output = SimpleNamespace(
            success=True,
            data={
                "target": "GitHub",
                "resolved_name": "GitHub Desktop",
                "resolved_path": local_result["path"],
                "type": "exe",
                "process_id": 0,
                "launch_time": "2026-04-04T00:00:00",
                "status": "launched",
            },
            error=None,
        )

        with (
            patch.object(tool.searcher, "search_local_app", return_value=local_result) as search_local_app,
            patch.object(tool.searcher, "resolve_website") as resolve_website,
            patch.object(tool, "_launch_result", AsyncMock(return_value=fake_output)) as launch_result,
        ):
            result = await tool.execute({"target": "GitHub", "destination": "auto"})

        self.assertTrue(result.success)
        self.assertEqual(result.data["status"], "launched")
        search_local_app.assert_called_once()
        resolve_website.assert_not_called()
        launch_result.assert_awaited_once()

    async def test_local_launch_uses_app_focus_tool_after_open(self):
        tool = AppOpenTool()
        local_result = {
            "name": "Calculator",
            "path": "C:/Windows/System32/calc.exe",
            "type": "exe",
            "launch_method": "run",
        }
        focus_output = SimpleNamespace(success=True, data={"focused": True}, error=None)

        with (
            patch.object(tool, "_shell_open") as shell_open,
            patch.object(tool.app_focus_tool, "execute", AsyncMock(return_value=focus_output)) as focus_execute,
        ):
            result = await tool._launch_result(target="calc", result=local_result, args=[])

        self.assertTrue(result.success)
        self.assertTrue(result.data["focused"])
        shell_open.assert_called_once_with(local_result["path"])
        focus_execute.assert_awaited_once()
        self.assertEqual(focus_execute.await_args.args[0]["target"], "Calculator")

    async def test_local_launch_passes_process_id_to_app_focus_when_available(self):
        tool = AppOpenTool()
        local_result = {
            "name": "Visual Studio Code",
            "path": "C:/Users/Aanand/AppData/Local/Programs/Microsoft VS Code/Code.exe",
            "type": "exe",
            "launch_method": "exec",
        }
        focus_output = SimpleNamespace(success=True, data={"focused": True}, error=None)

        with (
            patch.object(tool, "_launch_executable", return_value=4321) as launch_executable,
            patch.object(tool.app_focus_tool, "execute", AsyncMock(return_value=focus_output)) as focus_execute,
        ):
            result = await tool._launch_result(target="code", result=local_result, args=[])

        self.assertTrue(result.success)
        self.assertTrue(result.data["focused"])
        launch_executable.assert_called_once_with(local_result["path"], [], local_result["type"])
        focus_execute.assert_awaited_once()
        focus_inputs = focus_execute.await_args.args[0]
        self.assertEqual(focus_inputs["process_id"], 4321)
        self.assertEqual(focus_inputs["target"], "Visual Studio Code")

    async def test_missing_local_app_starts_async_web_fallback_check(self):
        tool = AppOpenTool()

        with (
            patch.object(tool.searcher, "search_local_app", return_value=None),
            patch.object(tool, "_speak_web_fallback_check_started") as speak_started,
            patch.object(tool, "_schedule_background_web_fallback") as schedule_background,
        ):
            result = await tool.execute(
                {
                    "target": "PC Manager",
                    "destination": "auto",
                    "_user_id": "u1",
                    "_task_id": "step_1",
                    "_execution_id": "exec_1",
                }
            )

        self.assertTrue(result.success)
        self.assertEqual(result.data["status"], "web_fallback_check_started")
        speak_started.assert_called_once_with(target="PC Manager", user_id="u1")
        schedule_background.assert_called_once_with(
            target="PC Manager",
            user_id="u1",
            task_id="step_1",
            execution_id="exec_1",
        )

    async def test_background_web_fallback_only_requests_approval_for_valid_site(self):
        tool = AppOpenTool()
        fake_emitter = SimpleNamespace(submit_approval_request=AsyncMock(return_value=True))

        with (
            patch.object(
                tool.searcher,
                "resolve_website",
                return_value={"name": "PC Manager", "path": "https://pcmanager.com", "type": "website"},
            ),
            patch.object(tool, "_validate_website_result", AsyncMock(return_value="https://pcmanager.com")),
            patch("app.agent.execution_gateway.get_task_emitter", return_value=fake_emitter),
        ):
            await tool._run_background_web_fallback(
                target="PC Manager",
                user_id="u1",
                task_id="step_1",
                execution_id="exec_1",
            )

        fake_emitter.submit_approval_request.assert_awaited_once()
        call = fake_emitter.submit_approval_request.await_args.kwargs
        self.assertEqual(call["user_id"], "u1")
        self.assertEqual(call["execution_id"], "exec_1")
        self.assertTrue(call["task_id"].startswith("step_1::web_fallback::"))

    async def test_background_web_fallback_rejects_invalid_site_without_prompt(self):
        tool = AppOpenTool()

        with (
            patch.object(
                tool.searcher,
                "resolve_website",
                return_value={"name": "PC Manager", "path": "https://pcmanager.com", "type": "website"},
            ),
            patch.object(tool, "_validate_website_result", AsyncMock(return_value=None)),
            patch.object(tool, "_speak_website_not_valid") as speak_invalid,
            patch("app.agent.execution_gateway.get_task_emitter") as get_task_emitter,
        ):
            await tool._run_background_web_fallback(
                target="PC Manager",
                user_id="u1",
                task_id="step_1",
                execution_id="exec_1",
            )

        speak_invalid.assert_called_once_with(target="PC Manager", user_id="u1")
        get_task_emitter.assert_not_called()


if __name__ == "__main__":
    unittest.main()
