"""TriggerHandler — fires reminders and recurring tasks when due."""
from __future__ import annotations

import logging

from app.kernel.contracts.models import KernelEvent
from app.kernel.eventing.event_bus import emit_kernel_event
from app.services.scheduler.models import ScheduledTask

logger = logging.getLogger(__name__)


class TriggerHandler:
    async def fire_reminder(self, task: ScheduledTask) -> None:
        """Send notification + socket event + kernel event for a reminder."""
        logger.info("Firing reminder: %s", task.label)

        # Desktop notification
        try:
            from app.agent.desktop_notifications import show_info_notification
            show_info_notification("⏰ Reminder", task.notification_text or task.label)
        except Exception as exc:
            logger.debug("Notification failed: %s", exc)

        # Socket event
        try:
            from app.socket.utils import socket_emit_to_users
            await socket_emit_to_users("reminder:fired", {
                "task_id": task.id,
                "label": task.label,
                "text": task.notification_text or task.label,
            }, [task.user_id])
        except Exception:
            pass

        # Kernel event for activity log
        await emit_kernel_event(KernelEvent(
            event_type="reminder_fired",
            user_id=task.user_id,
            task_id=task.id,
            status="completed",
            tool_name="set_reminder",
            payload={"label": task.label, "text": task.notification_text},
        ))

    async def fire_recurring(self, task: ScheduledTask) -> None:
        """Re-execute a stored task plan via the orchestrator + execution engine."""
        logger.info("Firing recurring task: %s", task.label)

        # Audit event regardless of whether a plan exists
        await emit_kernel_event(KernelEvent(
            event_type="scheduled_task_fired",
            user_id=task.user_id,
            task_id=task.id,
            status="started",
            tool_name="schedule_task",
            payload={
                "label": task.label,
                "step_count": len(task.task_plan or []),
                "cron": task.cron_expression,
            },
        ))

        # No plan → just notify like a reminder so the user is at least informed
        if not task.task_plan:
            await self.fire_reminder(task)
            return

        try:
            from app.agent.execution_gateway import (
                Task as KernelTask,
                get_client_executor,
                get_execution_engine,
                get_orchestrator,
                get_server_executor,
                get_task_emitter,
            )
            from app.config import settings

            tasks = [KernelTask(**t) for t in task.task_plan]

            orchestrator = get_orchestrator()
            engine = get_execution_engine()

            # If the user has an execution running, stop it cleanly first.
            if engine.is_running(task.user_id):
                await engine.stop_execution(task.user_id)
            await orchestrator.cleanup_user_state(task.user_id)
            await orchestrator.register_tasks(task.user_id, tasks)

            # Wire executors lazily — same pattern sqh_service uses
            if not engine.server_tool_executor:
                engine.set_server_executor(get_server_executor())
            engine.set_client_emitter(get_task_emitter())
            if settings.environment == "DESKTOP" and not engine.client_tool_executor:
                engine.set_client_executor(get_client_executor())

            await engine.start_execution(task.user_id)
            logger.info(
                "Recurring task %s started %d step(s) for user=%s",
                task.id, len(tasks), task.user_id,
            )
        except Exception as exc:
            logger.error(
                "fire_recurring failed for task=%s user=%s: %s",
                task.id, task.user_id, exc, exc_info=True,
            )
            await emit_kernel_event(KernelEvent(
                event_type="scheduled_task_fired",
                user_id=task.user_id,
                task_id=task.id,
                status="failed",
                tool_name="schedule_task",
                payload={"label": task.label, "error": str(exc)},
            ))
