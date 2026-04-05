import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

try:
    from app.agent.execution_gateway import init_execution_engine, init_orchestrator
    from app.kernel.execution.approval_coordinator import get_approval_coordinator, init_approval_coordinator
    from app.kernel.execution.execution_models import Task, TaskControl
    _IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - import gate
    init_execution_engine = None  # type: ignore[assignment]
    init_orchestrator = None  # type: ignore[assignment]
    get_approval_coordinator = None  # type: ignore[assignment]
    init_approval_coordinator = None  # type: ignore[assignment]
    Task = None  # type: ignore[assignment]
    TaskControl = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc


@unittest.skipIf(_IMPORT_ERROR is not None, f"Approval flow imports unavailable: {_IMPORT_ERROR}")
class NonBlockingApprovalFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.orchestrator = init_orchestrator()
        self.engine = init_execution_engine()
        init_approval_coordinator()

    async def test_task_level_approval_waits_non_blockingly_and_resumes(self):
        user_id = "approval_user"
        captured = {}

        async def _submit_approval_request(**kwargs):
            captured.update(kwargs)
            return True

        self.engine.set_client_emitter(
            SimpleNamespace(submit_approval_request=AsyncMock(side_effect=_submit_approval_request))
        )

        task = Task(
            task_id="step_1",
            tool="file_delete",
            execution_target="client",
            inputs={"path": "example.txt"},
            control=TaskControl(requires_approval=True, approval_question="Delete it?"),
        )
        await self.orchestrator.register_tasks(user_id, [task])
        record = self.orchestrator.get_task(user_id, "step_1")
        assert record is not None

        await self.orchestrator.mark_task_running(user_id, "step_1")
        should_continue = await self.engine._handle_approval_gate(user_id, record)

        self.assertFalse(should_continue)
        waiting_task = self.orchestrator.get_task(user_id, "step_1")
        assert waiting_task is not None
        self.assertEqual(waiting_task.status, "waiting")
        self.assertEqual(waiting_task.approval_state, "requested")
        self.assertTrue(waiting_task.approval_request_id)
        self.assertEqual(captured["task_id"], waiting_task.approval_request_id)

        await captured["on_response_callback"](user_id, waiting_task.approval_request_id, True)

        resumed_task = self.orchestrator.get_task(user_id, "step_1")
        assert resumed_task is not None
        self.assertEqual(resumed_task.status, "pending")
        self.assertEqual(resumed_task.approval_state, "approved")

        await self.orchestrator.mark_task_running(user_id, "step_1")
        should_continue_after_approval = await self.engine._handle_approval_gate(user_id, resumed_task)
        self.assertTrue(should_continue_after_approval)

    async def test_stale_approval_response_is_ignored_after_cancellation(self):
        coordinator = get_approval_coordinator()
        callback = AsyncMock()

        registered = coordinator.register_request(
            user_id="approval_user",
            request_id="stale_request",
            execution_id="exec_old",
            question="Continue?",
            callback=callback,
        )
        self.assertTrue(registered)

        cancelled = coordinator.cancel_user_requests("approval_user", execution_id="exec_old")
        self.assertGreaterEqual(cancelled, 1)

        resolved = await coordinator.resolve_request("approval_user", "stale_request", True)
        self.assertFalse(resolved)
        callback.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
