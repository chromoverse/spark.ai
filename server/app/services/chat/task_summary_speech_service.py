"""
Task Summary Speech Service

Builds the final spoken summary after task execution completes.

What makes this smarter than before:
- LLM receives the original user query as context → summary sounds like
  a direct reply to what the user asked, not a generic status report
- Language-aware: responds in the user's language (en/hi/ne)
- ack_hint used as a seed — LLM continues/improves it rather than ignoring it
- Richer deterministic fallback: uses output_preview across all completed
  tasks, not just single-task edge cases
- System/user prompt split for Groq caching
- Sanitize removed — stronger prompt means LLM doesn't leak tool names
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.agent.execution_gateway import get_orchestrator
from app.ai.providers import llm_chat
from app.config import settings

logger = logging.getLogger(__name__)

_LANG_MAP = {"hi": "Hindi", "ne": "Nepali", "en": "English"}

# ── Snapshot dataclass ─────────────────────────────────────────────────────────

@dataclass(slots=True)
class ExecutionSpeechSnapshot:
    user_id:  str
    summary:  Dict[str, int]
    tasks:    List[Dict[str, Any]]
    has_state: bool


# ── Static system prompt (cached by Groq) ─────────────────────────────────────

def _system_prompt(lang_label: str) -> str:
    return f"""You are a voice assistant giving a natural spoken completion update in {lang_label}.

Rules:
- Respond in {lang_label} only.
- 1–2 short sentences. Conversational, warm — not robotic or clinical.
- Ground every claim in the JSON facts provided. Never invent details.
- Describe WHAT happened in plain everyday language, not HOW it happened.
- Never mention: tool names (app_open, web_search, etc.), task IDs, execution targets, internal statuses.
- If failures > 0, mention them clearly but briefly.
- If the user's original query is provided, make the summary feel like a direct reply to it.
- If an ack_hint is provided, you may improve or continue it — but keep the same intent.
- Return plain text only. No markdown. No bullet points."""


# ── Service ────────────────────────────────────────────────────────────────────

class TaskSummarySpeechService:
    """
    Builds final spoken summary after task execution completes.

    Smarter than a plain status reporter:
    - Knows what the user originally asked (original_query context)
    - Responds in the user's language
    - Uses ack_hint as a seed, not just metadata
    - Rich deterministic fallback using output_preview across all tasks
    """

    async def build_summary_text(
        self,
        user_id: str,
        ack_hint: str = "",
        original_query: str = "",   # ← pass the user's original query for context
        user_lang: str = "en",
    ) -> str:
        snapshot_raw = await get_orchestrator().build_execution_speech_snapshot(user_id=user_id)
        snapshot     = _to_snapshot(snapshot_raw)
        lang_label   = _LANG_MAP.get(user_lang, "English")

        timeout_s = max(0.3, settings.FINAL_STATE_SUMMARY_LLM_TIMEOUT_MS / 1000.0)
        try:
            text = await asyncio.wait_for(
                self._llm_summary(snapshot, ack_hint, original_query, lang_label),
                timeout=timeout_s,
            )
            if text:
                return text
        except asyncio.TimeoutError:
            logger.warning("[Summary] LLM timed out — using fallback")
        except Exception as exc:
            logger.error("[Summary] LLM failed: %s", exc)

        return _fallback(snapshot, ack_hint, lang_label)

    async def _llm_summary(
        self,
        snapshot: ExecutionSpeechSnapshot,
        ack_hint: str,
        original_query: str,
        lang_label: str,
    ) -> str:
        # Only send what the LLM needs — no internal noise
        facts = {
            "summary":  snapshot.summary,
            "outcomes": [
                {
                    "status":  t.get("status"),
                    "preview": t.get("output_preview") or {},
                }
                for t in snapshot.tasks
                if t.get("status") in {"completed", "failed"}
            ],
        }

        # User message: grounded context the LLM uses to reply naturally
        user_parts = [f"Execution facts:\n{json.dumps(facts, ensure_ascii=False)}"]
        if original_query:
            user_parts.append(f"User's original request: \"{original_query}\"")
        if ack_hint:
            user_parts.append(f"Acknowledgment already sent: \"{ack_hint}\"")
        user_parts.append("Write the final spoken summary now.")

        messages = [
            {"role": "system", "content": _system_prompt(lang_label)},
            {"role": "user",   "content": "\n\n".join(user_parts)},
        ]

        raw, _ = await llm_chat(messages=messages, temperature=0.3, max_tokens=120)
        text   = " ".join((raw or "").strip().split())

        # Hard cap — TTS shouldn't speak a paragraph
        if len(text) > 220:
            text = text[:220].rstrip(" ,.;:") + "."

        return text


# ── Deterministic fallback ─────────────────────────────────────────────────────

def _fallback(snapshot: ExecutionSpeechSnapshot, ack_hint: str, lang_label: str) -> str:
    summary   = snapshot.summary
    total     = summary.get("total",     0)
    completed = summary.get("completed", 0)
    failed    = summary.get("failed",    0)

    if total == 0:
        return ack_hint.strip() or ("Nothing ran for that request." if lang_label == "English" else "कुछ नहीं चला।")

    # Collect human-readable outcomes from output_preview
    outcomes = _readable_outcomes(snapshot.tasks)

    # Failure cases
    if failed > 0 and completed == 0:
        return _localise("That request could not be completed.", lang_label)
    if failed > 0:
        done_str = f"{completed} task{'s' if completed != 1 else ''}"
        return _localise(f"Done, mostly — {done_str} completed, {failed} failed.", lang_label)

    # All succeeded — use outcomes if rich enough, else generic
    if outcomes:
        return _localise("Done. " + " ".join(outcomes), lang_label)

    if completed == 1:
        return _localise("Done. That's taken care of.", lang_label)

    return _localise(f"Done. Everything's been taken care of.", lang_label)


def _readable_outcomes(tasks: List[Dict[str, Any]]) -> List[str]:
    """
    Extract human-readable outcome lines from task output_preview dicts.
    Handles multiple completed tasks, not just single-task edge cases.
    """
    lines: List[str] = []
    for task in tasks:
        if task.get("status") != "completed":
            continue
        preview = task.get("output_preview")
        if not isinstance(preview, dict):
            continue

        target = (preview.get("target") or preview.get("resolved_name") or "").strip()
        status = str(preview.get("status", "")).strip().lower()

        if not target:
            continue

        if status == "opened_in_browser":
            lines.append(f"{target} is open in your browser.")
        elif status in {"launched", "opened"}:
            lines.append(f"{target} is open.")
        elif status == "closed":
            lines.append(f"{target} is closed.")
        elif status == "restarted":
            lines.append(f"{target} has been restarted.")
        elif status == "sent":
            lines.append(f"Message sent to {target}.")
        elif status in {"playing", "started"}:
            lines.append(f"{target} is playing.")
        else:
            lines.append(f"{target} is done.")

    return lines


def _localise(text: str, lang_label: str) -> str:
    """
    Minimal localisation for fallback strings.
    LLM handles real translation — this covers the deterministic path.
    """
    if lang_label == "Hindi":
        _HI = {
            "Done. That's taken care of.":          "हो गया।",
            "Done. Everything's been taken care of.": "सब हो गया।",
            "That request could not be completed.": "वो काम नहीं हो सका।",
            "Nothing ran for that request.":        "कुछ नहीं चला।",
        }
        return _HI.get(text, text)
    if lang_label == "Nepali":
        _NE = {
            "Done. That's taken care of.":          "भयो।",
            "Done. Everything's been taken care of.": "सब भयो।",
            "That request could not be completed.": "त्यो काम भएन।",
            "Nothing ran for that request.":        "केही चलेन।",
        }
        return _NE.get(text, text)
    return text


# ── Dataclass helper ───────────────────────────────────────────────────────────

def _to_snapshot(raw: Dict[str, Any]) -> ExecutionSpeechSnapshot:
    return ExecutionSpeechSnapshot(
        user_id=str(raw.get("user_id", "unknown")),
        summary=dict(raw.get("summary", {})),
        tasks=list(raw.get("tasks", [])),
        has_state=bool(raw.get("has_state", False)),
    )


# ── Singleton ──────────────────────────────────────────────────────────────────

_instance: Optional[TaskSummarySpeechService] = None


def get_task_summary_speech_service() -> TaskSummarySpeechService:
    global _instance
    if _instance is None:
        _instance = TaskSummarySpeechService()
    return _instance