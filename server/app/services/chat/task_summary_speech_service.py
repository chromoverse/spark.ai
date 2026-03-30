"""
Task Summary Speech Service

Builds the final spoken summary after task execution completes.

What makes this smarter than before:
- LLM receives the original user query as context → summary sounds like
  a direct reply to what the user asked, not a generic status report
- Language-aware: responds in the user's language (en/hi/ne)
- Richer deterministic fallback: uses structured output data across completed
  tasks instead of generic completion phrases
- System/user prompt split for Groq caching
- Stronger grounding prompt so the answer includes actual result data
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
from app.kernel.execution.failure_messages import normalize_failure

logger = logging.getLogger(__name__)

_LANG_MAP = {"hi": "Hindi", "ne": "Nepali", "en": "English"}

# ── Snapshot dataclass ─────────────────────────────────────────────────────────

@dataclass(slots=True)
class ExecutionSpeechSnapshot:
    user_id:  str
    summary:  Dict[str, Any]
    tasks:    List[Dict[str, Any]]
    has_state: bool


# ── Static system prompt (cached by Groq) ─────────────────────────────────────

def _system_prompt(lang_label: str) -> str:
    return f"""You are a voice assistant giving a natural spoken completion update in {lang_label}.

Rules:
- Respond in {lang_label} only.
- 1–4 short sentences. Conversational, warm — not robotic or clinical.
- Ground every claim in the JSON facts provided. Never invent details.
- Use the completed task outputs to answer the user's request directly.
- Describe WHAT the result is in plain everyday language, not HOW it happened.
- If the outputs contain concrete values, dates, counts, list items, or records, mention the most relevant few actual values.
- Never say only that data was fetched, retrieved, prepared, or found. Say the useful result itself.
- Never mention: tool names (app_open, web_search, etc.), task IDs, execution targets, internal statuses.
- If failures > 0, mention them clearly but briefly.
- If a failed item includes a user-facing message, prefer that reason and keep it non-technical.
- If the user's original query is provided, make the summary feel like a direct reply to it.
- Return plain text only. No markdown. No bullet points."""


# ── Service ────────────────────────────────────────────────────────────────────

class TaskSummarySpeechService:
    """
    Builds final spoken summary after task execution completes.

    Smarter than a plain status reporter:
    - Knows what the user originally asked (original_query context)
    - Responds in the user's language
    - Uses compact structured task outputs, not just status flags
    - Rich deterministic fallback using actual output data
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

        timeout_s = max(1.5, settings.FINAL_STATE_SUMMARY_LLM_TIMEOUT_MS / 1000.0)
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

        return _fallback(snapshot, ack_hint, user_lang, lang_label)

    async def _llm_summary(
        self,
        snapshot: ExecutionSpeechSnapshot,
        ack_hint: str,
        original_query: str,
        lang_label: str,
    ) -> str:
        # Only send what the LLM needs — no internal noise
        facts = {
            "summary": snapshot.summary,
            "results": [
                {
                    "status": t.get("status"),
                    "data": t.get("output_preview") or {},
                    "message": t.get("user_message") if t.get("status") == "failed" else None,
                }
                for t in snapshot.tasks
                if t.get("status") in {"completed", "failed"}
            ],
        }

        # User message: grounded context the LLM uses to reply naturally
        user_parts = [f"Execution facts:\n{json.dumps(facts, ensure_ascii=False)}"]
        if original_query:
            user_parts.append(f"User's original request: \"{original_query}\"")
        user_parts.append(
            "Write the final spoken answer now. Use the actual result data. "
            "If there are list items or records, summarize the most relevant few."
        )

        messages = [
            {"role": "system", "content": _system_prompt(lang_label)},
            {"role": "user",   "content": "\n\n".join(user_parts)},
        ]

        raw, _ = await llm_chat(messages=messages, temperature=0.25, max_tokens=220)
        text   = " ".join((raw or "").strip().split())

        # Hard cap — TTS shouldn't speak a paragraph
        if len(text) > 220:
            text = text[:220].rstrip(" ,.;:") + "."

        return text


# ── Deterministic fallback ─────────────────────────────────────────────────────

def _fallback(
    snapshot: ExecutionSpeechSnapshot,
    ack_hint: str,
    user_lang: str,
    lang_label: str,
) -> str:
    summary   = snapshot.summary
    total     = summary.get("total",     0)
    completed = summary.get("completed", 0)
    failed    = summary.get("failed",    0)
    failure_messages = _readable_failures(snapshot.tasks, user_lang)

    if total == 0:
        return ack_hint.strip() or ("Nothing ran for that request." if lang_label == "English" else "कुछ नहीं चला।")

    # Collect human-readable outcomes from output_preview
    outcomes = _readable_outcomes(snapshot.tasks)

    # Failure cases
    if failed > 0 and completed == 0 and failure_messages:
        return failure_messages[0]
    if failed > 0 and completed == 0:
        return _localise("That request could not be completed.", lang_label)
    if failed > 0 and failure_messages:
        return _partial_failure_intro(user_lang) + " " + failure_messages[0]
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
    """Render concise user-facing lines from structured output data."""
    lines: List[str] = []
    for task in tasks:
        if task.get("status") != "completed":
            continue
        preview = task.get("output_preview")
        if not preview:
            continue
        rendered = _render_preview(preview)
        if rendered:
            lines.append(rendered)

    return lines


def _render_preview(preview: Any) -> str:
    facts = _collect_fact_phrases(preview, limit=4)
    if not facts:
        return ""
    if len(facts) == 1:
        return facts[0] + "."
    if len(facts) == 2:
        return f"{facts[0]}; {facts[1]}."
    if len(facts) == 3:
        return f"{facts[0]}; {facts[1]}; {facts[2]}."
    return f"{facts[0]}; {facts[1]}; {facts[2]}; {facts[3]}."


def _collect_fact_phrases(value: Any, prefix: str = "", *, limit: int = 3) -> List[str]:
    phrases: List[str] = []

    def _add(item: str) -> None:
        cleaned = " ".join(item.split()).strip(" ,.;:")
        if cleaned and cleaned not in phrases and len(phrases) < limit:
            phrases.append(cleaned)

    if value is None:
        return phrases

    if isinstance(value, dict):
        entries = list(value.items())
        primitive_entries = [
            (key, item)
            for key, item in entries
            if not isinstance(item, (dict, list))
        ]
        structured_entries = [
            (key, item)
            for key, item in entries
            if isinstance(item, (dict, list))
        ]

        if structured_entries:
            ordered_entries = primitive_entries[:1] + structured_entries + primitive_entries[1:]
        else:
            ordered_entries = primitive_entries

        for key, item in ordered_entries:
            if len(phrases) >= limit:
                break
            if str(key).startswith("_"):
                continue
            label = _humanize_key(key)
            next_prefix = f"{prefix} {label}".strip() if prefix else label
            if isinstance(item, (str, int, float, bool)):
                _add(f"{next_prefix} {item}")
            elif item is None:
                continue
            else:
                child_phrases = _collect_fact_phrases(item, next_prefix, limit=limit - len(phrases))
                for child in child_phrases:
                    _add(child)
        return phrases

    if isinstance(value, list):
        for item in value:
            if len(phrases) >= limit:
                break
            if isinstance(item, (str, int, float, bool)):
                label = prefix or "item"
                _add(f"{label} {item}")
            else:
                child_phrases = _collect_fact_phrases(item, prefix, limit=limit - len(phrases))
                for child in child_phrases:
                    _add(child)
        return phrases

    if isinstance(value, (str, int, float, bool)):
        label = prefix or "result"
        _add(f"{label} {value}")

    return phrases


def _humanize_key(key: Any) -> str:
    text = str(key).replace("_", " ").replace("-", " ").strip()
    return re.sub(r"\s+", " ", text)


def _readable_failures(tasks: List[Dict[str, Any]], user_lang: str) -> List[str]:
    messages: List[str] = []
    for task in tasks:
        if task.get("status") != "failed":
            continue

        raw_error = str(task.get("raw_error") or task.get("error") or "").strip()
        tool_name = str(task.get("tool") or "").strip()

        if raw_error and user_lang != "en":
            message = normalize_failure(tool_name, raw_error, locale=user_lang)["user_message"]
        else:
            message = str(task.get("user_message") or "").strip()

        if message:
            messages.append(message)
    return messages


def _partial_failure_intro(user_lang: str) -> str:
    if user_lang == "hi":
        return "ज़्यादातर काम हो गया, लेकिन"
    if user_lang == "ne":
        return "धेरैजसो काम भयो, तर"
    return "Most of it worked, but"


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
