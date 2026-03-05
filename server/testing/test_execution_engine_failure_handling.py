import unittest
from types import SimpleNamespace

try:
    from app.kernel.execution.execution_engine import ExecutionEngine
    from app.kernel.execution.execution_models import Task, TaskOutput, TaskRecord
    _IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - environment-dependent import gate
    ExecutionEngine = None  # type: ignore[assignment]
    Task = None  # type: ignore[assignment]
    TaskOutput = None  # type: ignore[assignment]
    TaskRecord = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc


class _FakeOrchestrator:
    def __init__(self):
        self.completed: list[tuple[str, str, TaskOutput]] = []
        self.failed: list[tuple[str, str, str]] = []
        self.running: list[tuple[str, str]] = []

    async def mark_task_running(self, user_id: str, task_id: str) -> None:
        self.running.append((user_id, task_id))

    async def mark_task_completed(self, user_id: str, task_id: str, output: TaskOutput) -> None:
        self.completed.append((user_id, task_id, output))

    async def mark_task_failed(self, user_id: str, task_id: str, error: str) -> None:
        self.failed.append((user_id, task_id, error))

    def get_state(self, user_id: str):
        return SimpleNamespace()


class _FakeBindingResolver:
    @staticmethod
    def validate_bindings(task: TaskRecord, state):
        return True, None

    @staticmethod
    def resolve_inputs(task: TaskRecord, state):
        return dict(task.task.inputs)


class _FakeServerExecutor:
    def __init__(self, output: TaskOutput):
        self._output = output

    async def execute(self, task: TaskRecord) -> TaskOutput:
        return self._output


@unittest.skipIf(_IMPORT_ERROR is not None, f"Execution engine imports unavailable: {_IMPORT_ERROR}")
class ExecutionEngineFailureHandlingTests(unittest.IsolatedAsyncioTestCase):
    def _make_task(self) -> TaskRecord:
        return TaskRecord(
            task=Task(
                task_id="step_1",
                tool="message_send",
                execution_target="server",
                inputs={"contact": "daddy", "message": "hello"},
            )
        )

    async def test_server_task_marks_failed_when_tool_output_unsuccessful(self):
        engine = ExecutionEngine()
        fake_orchestrator = _FakeOrchestrator()
        engine.orchestrator = fake_orchestrator
        engine.binding_resolver = _FakeBindingResolver()
        engine.server_tool_executor = _FakeServerExecutor(
            TaskOutput(success=False, data={}, error="automation failed")
        )

        task = self._make_task()
        await engine._execute_single_server_task("u1", task)

        self.assertEqual(len(fake_orchestrator.completed), 0)
        self.assertEqual(len(fake_orchestrator.failed), 1)
        self.assertEqual(fake_orchestrator.failed[0][2], "automation failed")

    async def test_server_task_marks_completed_when_tool_output_successful(self):
        engine = ExecutionEngine()
        fake_orchestrator = _FakeOrchestrator()
        engine.orchestrator = fake_orchestrator
        engine.binding_resolver = _FakeBindingResolver()
        engine.server_tool_executor = _FakeServerExecutor(
            TaskOutput(success=True, data={"ok": True}, error=None)
        )

        task = self._make_task()
        await engine._execute_single_server_task("u1", task)

        self.assertEqual(len(fake_orchestrator.failed), 0)
        self.assertEqual(len(fake_orchestrator.completed), 1)


if __name__ == "__main__":
    unittest.main()
