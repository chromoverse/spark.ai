import asyncio
import tempfile
import unittest

try:
    from app.path.manager import PathManager
    from tools.tools.system.shell_agent import GuardedCommandRunner
    _IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - import gate
    PathManager = None  # type: ignore[assignment]
    GuardedCommandRunner = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc


@unittest.skipIf(_IMPORT_ERROR is not None, f"Shell agent imports unavailable: {_IMPORT_ERROR}")
class ShellAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_only_command_runs_without_approval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = GuardedCommandRunner(PathManager(env={"JARVIS_DATA_DIR": temp_dir}))
            result = await runner.run(
                command='Write-Output "hello"',
                working_dir=temp_dir,
                user_id="guest",
                task_id="task_1",
                step_index=1,
                allow_network=False,
            )

        self.assertTrue(result["allowed"])
        self.assertFalse(result["requires_approval"])
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("hello", result["stdout"].lower())

    async def test_destructive_command_requires_approval_and_denies_without_user_context(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = GuardedCommandRunner(PathManager(env={"JARVIS_DATA_DIR": temp_dir}))
            classification = runner.classify_command("Remove-Item test.txt", allow_network=False)
            self.assertTrue(classification["requires_approval"])
            self.assertTrue(classification["destructive"])

            result = await runner.run(
                command="Remove-Item test.txt",
                working_dir=temp_dir,
                user_id="guest",
                task_id="task_1",
                step_index=1,
                allow_network=False,
            )

        self.assertFalse(result["allowed"])
        self.assertTrue(result["requires_approval"])
        self.assertFalse(result["approved"])

    def test_network_command_is_blocked_when_not_allowed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = GuardedCommandRunner(PathManager(env={"JARVIS_DATA_DIR": temp_dir}))
            classification = runner.classify_command("Invoke-WebRequest https://example.com", allow_network=False)

        self.assertTrue(classification["blocked"])
        self.assertIn("Networked commands are blocked", classification["reason"])


if __name__ == "__main__":
    unittest.main()
