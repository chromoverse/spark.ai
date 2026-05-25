"""
SQH Service — Secondary Query Handler

1. Build execution plan via LLM
2. Register tasks with Orchestrator
3. Start Execution Engine
4. Emit final TTS summary after completion
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from app.agent.execution_gateway import (
    LifecycleMessages,
    Task,
    get_client_executor,
    get_execution_engine,
    get_orchestrator,
    get_server_executor,
    get_task_emitter,
)
from app.models.pqh_response_model import PQHResponse
from app.prompts.sqh_prompt import build_messages
from app.ai.providers import llm_chat, routed_chat
from app.config import settings
from app.kernel.execution.approval_coordinator import get_approval_coordinator
from app.kernel.execution.job_coordinator import (
    get_job_coordinator,
    JobQuotaExceeded,
    MAX_ACTIVE_JOBS_PER_USER,
)
from app.services.interrupt_manager import get_interrupt_manager
from .task_summary_speech_service import get_task_summary_speech_service
from .tool_output_delivery_service import get_tool_output_delivery_service

logger = logging.getLogger(__name__)
_interrupt = get_interrupt_manager()


# ── JSON extraction ────────────────────────────────────────────────────────────

def _looks_like_task(obj: Any) -> bool:
    return isinstance(obj, dict) and "tool" in obj and (
        "task_id" in obj or "inputs" in obj or "input_bindings" in obj
    )


def _count_tasks(candidate: Union[dict, list]) -> int:
    if isinstance(candidate, list):
        return sum(1 for x in candidate if _looks_like_task(x))
    if isinstance(candidate, dict):
        tasks = candidate.get("tasks")
        if isinstance(tasks, list):
            return sum(1 for x in tasks if _looks_like_task(x))
        if _looks_like_task(candidate):
            return 1
    return 0


def _best_candidate(candidates: List[Union[dict, list]]) -> Union[dict, list, None]:
    if not candidates:
        return None
    scored = [((_count_tasks(c), i), c) for i, c in enumerate(candidates)]
    best_score, best = max(scored, key=lambda x: x[0])
    if best_score[0] > 0:
        return best
    for c in reversed(candidates):
        if isinstance(c, dict) and ("tasks" in c or "acknowledge_answer" in c):
            return c
    return candidates[-1]


def extract_json(response: str) -> Union[dict, list, None]:
    if not response:
        return None
    cleaned = response.strip()
    candidates: List[Union[dict, list]] = []

    # Direct parse
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, (dict, list)):
            candidates.append(parsed)
    except json.JSONDecodeError:
        pass

    # Fenced blocks
    for m in re.finditer(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE):
        block = m.group(1).strip()
        try:
            parsed = json.loads(block)
            if isinstance(parsed, (dict, list)):
                candidates.append(parsed)
        except json.JSONDecodeError:
            pass

    # Bracket scan
    first = min(
        (cleaned.find(c) for c in "{[" if cleaned.find(c) != -1),
        default=-1,
    )
    if first != -1:
        fragment = cleaned[first:]
        for end in range(len(fragment), 0, -1):
            try:
                parsed = json.loads(fragment[:end])
                if isinstance(parsed, (dict, list)):
                    candidates.append(parsed)
                break
            except json.JSONDecodeError:
                pass

    # Trailing-comma repair
    fixed = re.sub(r",(\s*[\]}])", r"\1", cleaned)
    try:
        parsed = json.loads(fixed)
        if isinstance(parsed, (dict, list)):
            candidates.append(parsed)
    except json.JSONDecodeError:
        pass

    return _best_candidate(candidates)


def _unpack(data: Union[dict, list, None]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    if data is None:
        return [], None
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)], None
    if isinstance(data, dict):
        ack  = data.get("acknowledge_answer") if isinstance(data.get("acknowledge_answer"), str) else None
        raw  = data.get("tasks")
        if isinstance(raw, list):
            return [x for x in raw if isinstance(x, dict)], ack
        if _looks_like_task(data):
            return [data], ack
    return [], None


def _skill_user_inputs(pqh_response: PQHResponse) -> Dict[str, Any]:
    """Best-effort dict of values a skill's `inputs_from_user` can pull from."""
    query = (pqh_response.cognitive_state.user_query or "").strip()
    return {"query": query, "user_query": query, "text": query}


def _build_skill_template_hint(skill) -> str:
    """Build a prompt appendix that tells the LLM to use this exact DAG structure.

    The LLM still extracts inputs from the user query, but it doesn't need to
    invent the task_ids, depends_on, or input_bindings — those come from the
    skill definition.
    """
    import json as _json

    steps = []
    for s in skill.steps:
        step = {
            "task_id": s.task_id,
            "tool": s.tool,
            "execution_target": s.execution_target,
        }
        if s.depends_on:
            step["depends_on"] = s.depends_on
        if s.input_bindings:
            step["input_bindings"] = s.input_bindings
        if s.inputs_from_user:
            step["inputs"] = {k: "<FILL FROM QUERY>" for k in s.inputs_from_user}
        steps.append(step)

    template_json = _json.dumps({"tasks": steps}, indent=2)
    return (
        "\n\n━━━ SKILL TEMPLATE (USE THIS STRUCTURE) ━━━\n"
        "A pre-defined recipe matches this query. Use EXACTLY this task structure.\n"
        "Your ONLY job: fill in the \"inputs\" values by extracting them from the user query.\n"
        "Do NOT change task_ids, tools, depends_on, or input_bindings.\n"
        f"\n{template_json}\n"
    )


def _validate_skill_template_output(tasks: List[Task], skill) -> List[Task]:
    """Repair LLM output to match the skill template's structure.

    If the LLM deviated (wrong task_ids, missing bindings, extra steps), we
    force the template's structure back while keeping the LLM-extracted inputs.
    """
    template_steps = skill.steps
    if len(tasks) != len(template_steps):
        logger.warning(
            "[SQH] Skill template mismatch: expected %d tasks, got %d — forcing template.",
            len(template_steps), len(tasks),
        )

    # Map LLM-generated inputs by tool name (best-effort match)
    llm_inputs_by_tool: Dict[str, Dict[str, Any]] = {}
    for t in tasks:
        llm_inputs_by_tool.setdefault(t.tool, t.inputs)

    # Rebuild from template, injecting LLM-extracted inputs
    repaired: List[Task] = []
    for step in template_steps:
        inputs = dict(step.inputs)
        llm_inputs = llm_inputs_by_tool.get(step.tool, {})
        for k, v in llm_inputs.items():
            if not k.startswith("_") and v is not None:
                inputs[k] = v
        repaired.append(Task(
            task_id=step.task_id,
            tool=step.tool,
            execution_target=step.execution_target,
            depends_on=list(step.depends_on),
            inputs=inputs,
            input_bindings=dict(step.input_bindings),
        ))
    return repaired


# ── Main service ───────────────────────────────────────────────────────────────

async def process_sqh(pqh_response: PQHResponse, user_details: Dict[str, Any]) -> None:
    user_id  = str(user_details.get("_id", "guest"))
    user_lang = user_details.get("lang", "en")
    original_query = pqh_response.cognitive_state.user_query or ""

    try:
        # ── Skill short-circuit ──────────────────────────────────────────
        # If a registered skill's trigger pattern matches the query AND every
        # required tool is available, we can either:
        #   A) Fully bypass the LLM (if the skill's first step needs no user-
        #      extracted inputs — e.g. screenshot_and_open)
        #   B) Give the LLM the skill's DAG as a template so it only fills
        #      inputs (faster + more reliable than generating the whole plan)
        ack: Optional[str] = None
        tasks: List[Task] = []
        used_skill: bool = False
        skill_template_hint: str = ""
        try:
            from plugins import get_skill_engine
            requested = list(pqh_response.category) if pqh_response.category else []
            skill = get_skill_engine().match_skill(original_query, requested)
            if skill:
                # Check if the skill can run without LLM input extraction:
                # NO step has inputs_from_user → full bypass
                needs_llm_inputs = any(s.inputs_from_user for s in skill.steps)
                if not needs_llm_inputs:
                    tasks = get_skill_engine().expand_to_tasks(skill)
                    if tasks:
                        used_skill = True
                        ack = f"Got it."
                        logger.info(
                            "[SQH] skill full-bypass: %s (%d steps)",
                            skill.name, len(tasks),
                        )
                else:
                    # Provide the skill structure as a hint to the LLM so it
                    # only needs to fill in inputs (not invent the DAG).
                    skill_template_hint = _build_skill_template_hint(skill)
                    logger.info(
                        "[SQH] skill template hint: %s (LLM fills inputs)",
                        skill.name,
                    )
        except Exception as exc:
            logger.warning("[SQH] skill match raised, falling back to LLM: %s", exc)

        if used_skill:
            # Skip LLM plan generation entirely
            messages = []  # type: ignore[var-annotated]
            last_error = None
        else:
            # Pre-fetch connected services for tool filtering (best-effort — never blocks SQH)
            connected_services: List[str] = []
            try:
                from app.connectors.registry import get_all_connector_statuses
                statuses = await get_all_connector_statuses(user_id)
                connected_services = [s["id"] for s in statuses if s["connected"]]
            except Exception:
                pass  # Silently degrade — tool filtering is an optimization, not a hard requirement

            messages     = build_messages(
                pqh_response=pqh_response,
                user_lang=user_details.get("lang", "en"),
                user_preferences=user_details.get("preferences", {}),
                user_id=user_id,
                connected_services=connected_services,
            )
            # If a skill matched but needs LLM to fill inputs, append the
            # template as a strong hint so the LLM doesn't reinvent the DAG.
            if skill_template_hint:
                messages[-1]["content"] += skill_template_hint
            retry_limit  = 1 + max(0, int(getattr(settings, "SQH_PLAN_RETRY_ATTEMPTS", 1)))
            last_error: Optional[Exception] = None

            for attempt in range(1, retry_limit + 1):
                raw, _ = await routed_chat("streaming", messages=messages)

                try:
                    if not raw:
                        raise ValueError("empty LLM response")

                    data = extract_json(raw)
                    if data is None:
                        raise ValueError("no valid JSON in response")

                    tasks_data, ack = _unpack(data)
                    tasks = [Task(**t) for t in tasks_data]

                    if not tasks:
                        raise ValueError("no tasks in plan")

                    # If a skill template was used, validate the LLM respected it.
                    if skill_template_hint and skill:
                        tasks = _validate_skill_template_output(tasks, skill)

                    last_error = None
                    break

                except Exception as exc:
                    last_error = exc
                    logger.warning("[SQH] attempt %d/%d failed: %s", attempt, retry_limit, exc)
                    if attempt >= retry_limit:
                        break
                    # Append retry instruction to last user message
                    messages = messages[:-1] + [{
                        "role": "user",
                        "content": (
                            messages[-1]["content"]
                            + "\n\nRETRY: Previous output was invalid. "
                            "Return ONLY raw JSON. `tasks` must be a non-empty array. "
                            "No markdown, no explanation."
                        ),
                    }]

        if last_error or not tasks:
            raise ValueError(str(last_error or "no tasks generated"))

        # ── Register job + start execution ────────────────────────────────
        job_coordinator = get_job_coordinator()
        job_id, queued = job_coordinator.register_job(user_id, goal=original_query)

        if queued:
            # Slot full — job is queued; it will auto-start when a slot opens.
            _tasks, _ack, _query, _lang = list(tasks), ack, original_query, user_lang

            async def _start_queued():
                await _launch_job(user_id, _tasks, _ack, _query, _lang, job_id)

            job_coordinator.set_start_callback(user_id, job_id, _start_queued)

            from app.socket.utils import socket_emit
            queue_pos = len(job_coordinator.get_queued_jobs(user_id))
            await socket_emit("spark:message", {
                "user_id": user_id,
                "text": (
                    f"All {MAX_ACTIVE_JOBS_PER_USER} slots are busy. "
                    f"I've queued your request — it'll start automatically when a slot opens up."
                ),
            }, user_id=user_id)
            await socket_emit("job:queued", {
                "user_id": user_id, "job_id": job_id,
                "goal": original_query[:200],
                "position": queue_pos,
            }, user_id=user_id)
            return

        # Active slot available — launch immediately
        await _launch_job(user_id, tasks, ack, original_query, user_lang, job_id)

    except Exception as exc:
        logger.error("[SQH] critical failure user=%s: %s", user_id, exc, exc_info=True)
        raise


# ── Job launcher (shared by direct + queued-promotion paths) ──────────────────

async def _launch_job(
    user_id: str,
    tasks: List[Task],
    ack: Optional[str],
    original_query: str,
    user_lang: str,
    job_id: str,
) -> None:
    """Register tasks with orchestrator and start execution engine for a job."""
    orchestrator = get_orchestrator()
    execution_engine = get_execution_engine()

    await orchestrator.register_tasks(user_id, tasks, job_id=job_id)

    # Emit plan to live logs
    from app.socket.log_stream import emit_spark_log
    tool_names = [t.tool for t in tasks]
    await emit_spark_log(user_id, "plan_created", payload={
        "tools": tool_names, "task_count": len(tasks),
        "job_id": job_id,
        "query": original_query[:200],
        "message": f"Plan: {', '.join(tool_names)}",
    })

    # Emit job:started event
    try:
        from app.socket.utils import socket_emit
        await socket_emit("job:started", {
            "user_id": user_id, "job_id": job_id,
            "goal": original_query[:200],
        }, user_id=user_id)
    except Exception:
        pass

    if not execution_engine.server_tool_executor:
        execution_engine.set_server_executor(get_server_executor())
    execution_engine.set_client_emitter(get_task_emitter())

    if settings.environment == "DESKTOP":
        if not execution_engine.client_tool_executor:
            execution_engine.set_client_executor(get_client_executor())

    await execution_engine.start_execution(user_id, job_id=job_id)

    # Emit TTS summary after execution finishes
    asyncio.create_task(
        _emit_summary(user_id, ack or "", execution_engine, original_query, user_lang, job_id=job_id)
    )


# ── Post-execution TTS summary ─────────────────────────────────────────────────

async def _emit_summary(
    user_id: str,
    ack_hint: str,
    execution_engine: Any,
    original_query: str = "",
    user_lang: str = "en",
    job_id: str = "default",
) -> None:
    """Wait for execution to complete, then emit final TTS summary (only when meaningful)."""
    engine_key = f"{user_id}:{job_id}"
    try:
        event = execution_engine.completion_events.get(engine_key)
        if event:
            await asyncio.wait_for(event.wait(), timeout=60)
    except asyncio.TimeoutError:
        logger.warning("[SQH] completion wait timed out for %s — emitting anyway", engine_key)
    except Exception as exc:
        logger.error("[SQH] completion wait error %s: %s", engine_key, exc)

    # Emit job lifecycle event + push entity results directly
    try:
        from app.socket.utils import socket_emit
        orchestrator = get_orchestrator()
        summary_data = await orchestrator.get_execution_summary(user_id, job_id=job_id)
        if summary_data.get("failed", 0) > 0:
            await socket_emit("job:failed", {
                "user_id": user_id, "job_id": job_id,
                "error": f"{summary_data['failed']} task(s) failed",
            }, user_id=user_id)
        else:
            await socket_emit("job:completed", {
                "user_id": user_id, "job_id": job_id,
            }, user_id=user_id)

        # Push ALL completed tool outputs directly (no round-trip needed).
        # Iterate the job's own state so we never deliver stale data from
        # a different job.
        job_state = orchestrator.get_state(user_id, job_id=job_id)
        logger.info("[SQH] _emit_summary: job_state=%s for user=%s job=%s", "found" if job_state else "NONE", user_id, job_id)
        if job_state:
            delivery = get_tool_output_delivery_service()
            for _t in job_state.tasks.values():
                if _t.status != "completed" or not _t.output or not _t.output.data:
                    logger.info("[SQH] Skipping task %s — status=%s has_output=%s", _t.task_id, _t.status, bool(_t.output and _t.output.data))
                    continue
                try:
                    output = await delivery.get_output(
                        user_id=user_id, task_id=_t.task_id,
                        include_full=True,
                        job_id=job_id,
                    )
                    if output and output.get("data"):
                        logger.info("[SQH] Pushing tool:output for %s (tool=%s) keys=%s", _t.task_id, _t.tool, list(output["data"].keys()))
                        await socket_emit("tool:output", {
                            "success": True, "output": output,
                        }, user_id=user_id)
                    else:
                        logger.warning("[SQH] No data in delivery output for %s", _t.task_id)
                except Exception as _exc:
                    logger.error("[SQH] Error pushing tool:output for %s: %s", _t.task_id, _exc)
    except Exception:
        pass

    # Skip if user already interrupted (started speaking again)
    if _interrupt.is_set(user_id):
        logger.info("⏭️ Skipping summary TTS — user %s interrupted", user_id)
        return

    try:
        # Smart gate: decide if summary is worth speaking
        orchestrator = get_orchestrator()
        snapshot_raw = await orchestrator.build_execution_speech_snapshot(user_id=user_id, job_id=job_id)
        if not _should_speak(snapshot_raw, original_query):
            logger.info("⏭️ Skipping summary TTS — no tool needs summary for user=%s", user_id)
            return

        summary = ack_hint.strip()
        if settings.FINAL_STATE_SUMMARY_TTS_ENABLED:
            summary = await get_task_summary_speech_service().build_summary_text(
                user_id=user_id,
                ack_hint=ack_hint,
                original_query=original_query,
                user_lang=user_lang,
                job_id=job_id,
            )

        if not summary:
            return

        # Save to conversation history so follow-up queries have context
        from app.cache import add_message
        await add_message(user_id=user_id, role="user", content=original_query)
        await add_message(user_id=user_id, role="assistant", content=summary)

        # Final interrupt check before speaking
        if _interrupt.is_set(user_id):
            logger.info("⏭️ Skipping summary TTS (post-build) — user %s interrupted", user_id)
            return

        # Emit the summary text to the UI so users can read what Spark says
        from app.socket.log_stream import emit_spark_log
        await emit_spark_log(user_id, "summary", job_id=job_id, payload={"message": summary})

        from app.socket.utils import stream_tts_to_client
        await stream_tts_to_client(summary, user_id=user_id)

    except Exception as exc:
        logger.error("[SQH] summary emit failed user=%s: %s", user_id, exc)


# ── Smart gate: should we speak the summary? ────────────────────────────────────────

# Intents that are pure search/lookup — user expects a spoken result
_SEARCH_INTENTS = {
    "hotel_search", "product_search", "restaurant_search",
    "local_service", "factual_lookup", "research",
}


def _tool_wants_summary_tts(tool_name: str, output_preview: Dict[str, Any] = {}) -> bool:
    """
    Check the tool registry's summary_tts flag for a given tool.

    Supports:
      - True/False: static always/never
      - "intent_search": speak only when output intent is a search/lookup intent
    """
    from app.plugins.tools.registry_loader import get_tool_registry
    registry = get_tool_registry()
    meta = registry.get_tool(tool_name)
    if meta is None:
        return False
    flag = meta.metadata.get("summary_tts", False)
    if flag is True:
        return True
    if flag == "intent_search":
        intent = str(output_preview.get("intent", "")).lower()
        return intent in _SEARCH_INTENTS
    return False


def _should_speak(snapshot_raw: Dict[str, Any], original_query: str = "") -> bool:
    """
    Registry-driven gate: speak only when a tool's summary_tts flag is true,
    or when there are failures. No hardcoded tool lists.

    No LLM call — pure dict + registry inspection, ~0 latency.
    """
    summary = snapshot_raw.get("summary", {})
    tasks = snapshot_raw.get("tasks", [])
    failed    = summary.get("failed", 0)

    logger.info("[_should_speak] summary=%s  tasks_count=%d", summary, len(tasks))

    # Always speak if there's a failure
    if failed > 0:
        logger.info("[_should_speak] speaking — %d failure(s)", failed)
        return True

    # Check if ANY completed tool has summary_tts=true in the registry
    for task in tasks:
        status = task.get("status")
        tool = str(task.get("tool") or task.get("task", {}).get("tool", "")).strip()
        if status != "completed":
            logger.info("[_should_speak] skip task %s status=%s", tool, status)
            continue
        output_preview = task.get("output_preview") or {}
        wants = _tool_wants_summary_tts(tool, output_preview) if tool else False
        logger.info("[_should_speak] tool=%s  summary_tts=%s  intent=%s", tool, wants, output_preview.get("intent"))
        if wants:
            logger.info("[_should_speak] speaking — tool '%s' wants summary", tool)
            return True

    # No tool needs summary TTS → skip
    logger.info("[_should_speak] silent — no tool needs summary TTS")
    return False
