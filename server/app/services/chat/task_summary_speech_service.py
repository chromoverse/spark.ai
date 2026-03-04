from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.agent.execution_gateway import get_orchestrator
from app.ai.providers import llm_chat
from app.config import settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ExecutionSpeechSnapshot:
    """
    Compact execution snapshot used for speech synthesis.

    Internal service-only type so final TTS text is grounded in real execution
    state and not inferred from prompt memory.
    """

    user_id: str
    summary: Dict[str, int]
    tasks: List[Dict[str, Any]]
    has_state: bool


class TaskSummarySpeechService:
    """
    Builds final spoken summary after task execution completes.

    Policy:
    - LLM-first summary generation from execution facts
    - deterministic fallback on timeout/error/empty output
    """

    async def build_summary_text(self, user_id: str, ack_hint: str = "") -> str:
        start = time.perf_counter()

        snapshot_raw = await get_orchestrator().build_execution_speech_snapshot(user_id=user_id)
        snapshot = self._to_snapshot(snapshot_raw)

        timeout_s = max(0.3, settings.FINAL_STATE_SUMMARY_LLM_TIMEOUT_MS / 1000.0)
        llm_started = time.perf_counter()
        try:
            text = await asyncio.wait_for(
                self._generate_llm_summary(snapshot=snapshot, ack_hint=ack_hint),
                timeout=timeout_s,
            )
            llm_ms = (time.perf_counter() - llm_started) * 1000
            if text:
                logger.info("🧠 [SQH] Final speech summary generated via LLM in %.0fms", llm_ms)
                total_ms = (time.perf_counter() - start) * 1000
                logger.info("🗣️ [SQH] Final summary text ready in %.0fms", total_ms)
                return text
        except asyncio.TimeoutError:
            logger.warning("⏱️ [SQH] Final speech LLM timed out at %.0fms", timeout_s * 1000)
        except Exception as exc:
            logger.error("❌ [SQH] Final speech LLM generation failed: %s", exc, exc_info=True)

        fallback = self._build_fallback_summary(snapshot=snapshot, ack_hint=ack_hint)
        total_ms = (time.perf_counter() - start) * 1000
        logger.info("🛟 [SQH] Using fallback final summary (%.0fms)", total_ms)
        return fallback

    async def _generate_llm_summary(
        self,
        snapshot: ExecutionSpeechSnapshot,
        ack_hint: str,
    ) -> str:
        payload = {
            "summary": snapshot.summary,
            "tasks": snapshot.tasks,
            "ack_hint": ack_hint,
        }
        payload_json = json.dumps(payload, ensure_ascii=False)

        prompt = (
            "You are a helpful assistant giving a natural spoken completion update.\n"
            "Use ONLY the provided JSON facts. Do not invent details.\n"
            "Speak like a real person, not a system logger.\n"
            "Keep it concise, but do not sound clipped or robotic.\n"
            "You may use one or two short sentences if needed.\n"
            "Never mention internal IDs, execution targets, or tool names like app_open/web_research.\n"
            "If failures > 0, mention failure count clearly.\n"
            "If all succeeded, describe what got done in plain everyday language.\n"
            "Avoid phrases like 'all tasks completed successfully' unless absolutely necessary.\n"
            "Return plain text only.\n\n"
            f"JSON:\n{payload_json}\n"
        )

        result, provider = await llm_chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.35,
            max_tokens=140,
        )
        text = self._sanitize_text(" ".join((result or "").strip().split()))
        if len(text) > 240:
            text = text[:240].rstrip(" ,.;:") + "."
        logger.debug("LLM summary provider=%s text=%s", provider, text)
        return text

    def _build_fallback_summary(
        self,
        snapshot: ExecutionSpeechSnapshot,
        ack_hint: str,
    ) -> str:
        summary = snapshot.summary
        total = summary.get("total", 0)
        completed = summary.get("completed", 0)
        failed = summary.get("failed", 0)

        if total == 0:
            return ack_hint.strip() or "Nothing ran for that request."

        if failed > 0:
            if completed > 0:
                return f"I finished {completed} task{'s' if completed != 1 else ''}, but {failed} {'tasks' if failed != 1 else 'task'} could not be completed."
            return f"I could not complete that request because {failed} {'tasks' if failed != 1 else 'task'} failed."

        single_task_line = self._single_task_fallback(snapshot.tasks)
        if single_task_line:
            return single_task_line

        if completed == 1:
            return "Done. That request is complete."

        return f"Done. Everything requested has been completed ({completed} tasks)."

    @staticmethod
    def _single_task_fallback(tasks: List[Dict[str, Any]]) -> str:
        completed_tasks = [task for task in tasks if task.get("status") == "completed"]
        if len(completed_tasks) != 1:
            return ""

        task = completed_tasks[0]
        preview = task.get("output_preview")
        if not isinstance(preview, dict):
            return ""

        target = preview.get("target") or preview.get("resolved_name")
        status = str(preview.get("status", "")).strip().lower()

        if isinstance(target, str) and target.strip():
            clean_target = target.strip()
            if status == "opened_in_browser":
                return f"Done. I opened {clean_target} in your browser."
            if status in {"launched", "opened", "restarted", "closed"}:
                return f"Done. {clean_target} is now handled."
            return f"Done. {clean_target} is done."
        return ""

    @staticmethod
    def _sanitize_text(text: str) -> str:
        if not text:
            return ""
        cleaned = re.sub(r"\bfor\s+(client|server)\b", "", text, flags=re.IGNORECASE)
        cleaned = re.sub(r"\busing\s+[a-z0-9_]+\s+tool\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b([a-z]+_[a-z0-9_]+)\b", lambda m: m.group(1).replace("_", " "), cleaned)
        cleaned = re.sub(
            r"\ball tasks completed successfully\b",
            "everything is done",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,.;:")
        if cleaned and cleaned[-1] not in ".!?":
            cleaned += "."
        return cleaned

    @staticmethod
    def _to_snapshot(raw: Dict[str, Any]) -> ExecutionSpeechSnapshot:
        return ExecutionSpeechSnapshot(
            user_id=str(raw.get("user_id", "unknown")),
            summary=dict(raw.get("summary", {})),
            tasks=list(raw.get("tasks", [])),
            has_state=bool(raw.get("has_state", False)),
        )


_task_summary_speech_service: Optional[TaskSummarySpeechService] = None


def get_task_summary_speech_service() -> TaskSummarySpeechService:
    global _task_summary_speech_service
    if _task_summary_speech_service is None:
        _task_summary_speech_service = TaskSummarySpeechService()
    return _task_summary_speech_service
