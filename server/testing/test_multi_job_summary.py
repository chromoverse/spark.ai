"""
Test: Multi-job execution summary scoping

Reproduces the "Done: 0/1 succeeded" bug where _print_final_summary
called get_execution_summary(user_id) without job_id, causing
_find_any_state to return the wrong job's state when multiple
concurrent jobs exist for the same user.

The fix: always pass job_id to get_execution_summary so it does a
direct key lookup (user_id:job_id) instead of iterating over states.
"""

import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(message)s")
logger = logging.getLogger(__name__)

from app.kernel.execution.orchestrator import TaskOrchestrator
from app.kernel.execution.execution_models import Task, TaskOutput


def test_multi_job_summary_scoping():
    """
    Scenario:
    - User has two concurrent jobs (job_a, job_b) registered under
      {user_id}:{job_id} keys.
    - Job A has 3 tasks, 1 completed.
    - Job B has 2 tasks, 0 completed.
    - Job B was registered FIRST (dict insertion order matters).

    Expected bug behavior:
      get_execution_summary(user_id) WITHOUT job_id → returns job B's state
      (first found via _find_any_state) → total=2, completed=0
      This is WRONG if you're asking about job A.

    Expected fixed behavior:
      get_execution_summary(user_id, job_id="job_a") → returns job A's state
      → total=3, completed=1
    """
    orchestrator = TaskOrchestrator()
    user_id = "multi_job_test_user"

    # Register job_b FIRST so it appears first in dict iteration
    tasks_b = [
        Task(task_id="task_b1", tool="web_search", execution_target="server",
             depends_on=[], inputs={"query": "test b1"}),
        Task(task_id="task_b2", tool="web_search", execution_target="server",
             depends_on=[], inputs={"query": "test b2"}),
    ]
    asyncio.run(orchestrator.register_tasks(user_id, tasks_b, job_id="job_b"))

    # Register job_a SECOND
    tasks_a = [
        Task(task_id="task_a1", tool="web_search", execution_target="server",
             depends_on=[], inputs={"query": "test a1"}),
        Task(task_id="task_a2", tool="web_search", execution_target="server",
             depends_on=[], inputs={"query": "test a2"}),
        Task(task_id="task_a3", tool="web_search", execution_target="server",
             depends_on=[], inputs={"query": "test a3"}),
    ]
    asyncio.run(orchestrator.register_tasks(user_id, tasks_a, job_id="job_a"))

    # Complete 1 task in job_a only
    output = TaskOutput(success=True, data={"result": "ok"})
    asyncio.run(orchestrator.mark_task_completed(user_id, "task_a1", output, job_id="job_a"))

    # ========== BUG DEMO: Without job_id returns wrong state ==========
    summary_no_job = asyncio.run(orchestrator.get_execution_summary(user_id))
    logger.info("Summary WITHOUT job_id: completed=%s/%s (state=%s)",
                summary_no_job["completed"], summary_no_job["total"],
                "job_b" if summary_no_job["total"] == 2 else "unknown")

    # _find_any_state returns first found (job_b, inserted first)
    assert summary_no_job["total"] == 2, \
        f"Expected total=2 (job_b, first-found), got {summary_no_job['total']}"
    assert summary_no_job["completed"] == 0, \
        f"Expected completed=0 (job_b, nothing completed), got {summary_no_job['completed']}"

    # ========== FIX VERIFICATION: With job_id returns correct state ==========
    summary_job_a = asyncio.run(orchestrator.get_execution_summary(user_id, job_id="job_a"))
    logger.info("Summary WITH job_id='job_a': completed=%s/%s",
                summary_job_a["completed"], summary_job_a["total"])
    assert summary_job_a["total"] == 3, \
        f"Expected total=3 for job_a, got {summary_job_a['total']}"
    assert summary_job_a["completed"] == 1, \
        f"Expected completed=1 for job_a, got {summary_job_a['completed']}"

    summary_job_b = asyncio.run(orchestrator.get_execution_summary(user_id, job_id="job_b"))
    logger.info("Summary WITH job_id='job_b': completed=%s/%s",
                summary_job_b["completed"], summary_job_b["total"])
    assert summary_job_b["total"] == 2, \
        f"Expected total=2 for job_b, got {summary_job_b['total']}"
    assert summary_job_b["completed"] == 0, \
        f"Expected completed=0 for job_b, got {summary_job_b['completed']}"

    logger.info("\n✅ ALL ASSERTIONS PASSED")
    logger.info("  - Without job_id: returns first-found state (job_b) — the bug")
    logger.info("  - With job_id='job_a': correctly returns job_a's state")
    logger.info("  - With job_id='job_b': correctly returns job_b's state")
    logger.info("  - Fix verified: passing job_id ensures correct scoping")


if __name__ == "__main__":
    test_multi_job_summary_scoping()
