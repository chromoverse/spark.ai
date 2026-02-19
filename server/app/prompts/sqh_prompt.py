"""SQH - Secondary Query Handler
Generates execution plans (Task arrays) based on PQH analysis.
"""

import json
from typing import Optional, Dict, Any

from app.agent.shared.registry.loader import get_tool_registry
from app.models.pqh_response_model import PQHResponse


def get_tools_schema(tool_names: list[str]) -> dict[str, dict]:
    """Get schemas for the specified tools from registry."""
    tool_registry = get_tool_registry()
    return {
        name: tool.__dict__
        for name in tool_names
        if (tool := tool_registry.get_tool(name))
    }


def build_sqh_prompt(
    pqh_response: PQHResponse,
    user_lang: str = "en",                        # Primary lang for ack/lifecycle messages
    user_preferences: Optional[Dict[str, Any]] = None       # {"movies": ["netflix"], "browser": ["chrome"], ...}
) -> str:
    """
    Builds the SQH system prompt.

    Args:
        pqh_response:      Full PQH response model.
        user_lang:         Language code for output ("en", "hi", "ne").
        user_preferences:  User's preferred apps/services per category.
                           e.g. {"browser": ["chrome"], "movies": ["netflix", "youtube"]}
                           Falls back to stable defaults if empty or missing.
    """

    # ── 1. Unpack PQH context ──────────────────────────────────────────────
    c_state        = pqh_response.cognitive_state
    user_query     = c_state.user_query
    thought_process = c_state.thought_process
    pqh_answer     = c_state.answer
    tool_names     = pqh_response.requested_tool or []

    # ── 2. Language config ─────────────────────────────────────────────────
    LANG_MAP = {
        "hi": "Hindi",
        "ne": "Nepali",
        "en": "English",
    }
    lang_label = LANG_MAP.get(user_lang, "English")
    # Second language is always English as fallback for clarity
    secondary_lang = "English" if user_lang != "en" else "Hindi"

    # ── 3. User preferences ────────────────────────────────────────────────
    prefs = user_preferences or {}
    prefs_json = json.dumps(prefs, indent=2) if prefs else "None provided"

    # ── 4. Tool schemas ────────────────────────────────────────────────────
    tool_schemas     = get_tools_schema(tool_names)
    tool_schemas_json = json.dumps(tool_schemas, indent=2)

    # ── 5. Prompt ──────────────────────────────────────────────────────────
    return f"""You are SQH (Secondary Query Handler).
Your job: read the PQH analysis, then return a precise JSON execution plan.

━━━ INPUT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
User Query        : "{user_query}"
PQH Thought       : "{thought_process}"
PQH Answer (sent) : "{pqh_answer}"

━━━ USER PREFERENCES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{prefs_json}

PREFERENCE RULES:
- When a task involves opening an app, browser, streaming service, or any
  category-specific tool, CHECK preferences first.
- Example: query = "play a movie" → check preferences["movies"] → use first
  entry (e.g. "netflix"). If empty → default to the most universally stable
  option (e.g. "youtube" for media, "chrome" for browser, "notepad" for text).
- Never invent a preference. Only use what's listed or a safe default.

━━━ AVAILABLE TOOLS (schemas) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{tool_schemas_json}

Use ONLY the tools listed above. Map every task to an exact tool name from this set.

━━━ OUTPUT FORMAT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return a raw JSON object — no markdown, no code fences:
{{
  "acknowledge_answer": "...",
  "tasks": [...]
}}

━━━ ACKNOWLEDGE ANSWER RULES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Language  : {lang_label} (you may sprinkle {secondary_lang} naturally if it fits).
Tone      : Warm, natural, conversational assistant — NOT robotic.
Tense     : Completed/initiated action — treat it as done.
Variation : Be RANDOM and human. Rotate between styles, for example:
  • "Done, Sir! Anything else?"
  • "Sir, I've taken care of it."
  • "All set! Let me know if you need anything more."
  • "Consider it done, Boss."
  • "That's handled! What's next?"
  • (or any natural equivalent in {lang_label})
  Never repeat the same phrasing pattern twice in a session.
Length    : 1–2 short sentences max.

━━━ TASK OBJECT SCHEMA ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Each task must follow:
{{
  "task_id"          : "step_1",          // Unique (step_1, step_2 ...)
  "tool"             : "exact_tool_name", // From Available Tools only
  "execution_target" : "client",          // or "server" per tool schema
  "depends_on"       : [],               // task_ids this waits for
  "inputs"           : {{                  // Static, schema-matched inputs
    "arg_name": "value"
  }},
  "input_bindings"   : {{                  // Dynamic from prior task output
    "arg_name": "$.tasks.step_1.output.data.field"
  }},
  "lifecycle_messages": {{
    "on_start"  : "...",  // Action started  — {lang_label}, natural
    "on_success": "...",  // Action done     — {lang_label}, natural
    "on_failure": "..."   // Action failed   — {lang_label}, natural
  }},
  "control": {{
    "requires_approval": false,
    "on_failure": "abort"   // or "continue"
  }}
}}

━━━ LIFECYCLE MESSAGE RULES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Language   : {lang_label} (mix {secondary_lang} only if natural).
- Tone       : Concise, action-oriented, friendly.
- Format     : Action + optional filler — keep it short.
  Examples   : "Opening Chrome...", "File banaya!", "Search ho gaya Boss."

━━━ EXECUTION INSTRUCTIONS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Analyze query + PQH thought to understand full intent.
2. Resolve any app/service ambiguity using preferences (fallback to defaults).
3. Break intent into atomic, ordered tasks — each mapped to one tool.
4. Set correct depends_on chains for sequential steps.
5. Build lifecycle_messages per task in {lang_label}.
6. Write acknowledge_answer last, after confirming tasks are complete.
7. Return ONLY the raw JSON. Nothing else.
"""