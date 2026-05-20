"""
SQH Prompt — Execution Plan Generator

Two-part messages structure:

  [system]  → output format, task schema, rules  (static → Groq caches it)
  [user]    → PQH analysis + tool schemas + preferences  (changes per call)

Only the user message changes per request, so the system prompt
prefix-caches across all SQH calls.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.plugins.tools.registry_loader import get_tool_registry
from app.models.pqh_response_model import PQHResponse


def get_tools_schema(tool_names: List[str]) -> Dict[str, dict]:
    registry = get_tool_registry()
    return {
        name: tool.__dict__
        for name in tool_names
        if (tool := registry.get_tool(name))
    }


def _get_system_paths() -> str:
    """Return well-known OS paths so the LLM never needs to ask the user."""
    import os
    from pathlib import Path

    home = Path.home()
    paths = {
        "home": str(home),
        "desktop": str(home / "Desktop"),
        "downloads": str(home / "Downloads"),
        "documents": str(home / "Documents"),
        "pictures": str(home / "Pictures"),
        "music": str(home / "Music"),
        "videos": str(home / "Videos"),
    }
    # Windows-specific
    appdata = os.environ.get("APPDATA")
    if appdata:
        paths["appdata"] = appdata

    return "\n".join(f"  {k}: {v}" for k, v in paths.items())


# ── Static system prompt — cached by Groq ─────────────────────────────────────

def build_system_prompt(lang_label: str, secondary_lang: str) -> str:
    """
    Static rules for SQH. Lang labels are passed in but the structure
    never changes — so caching still applies within the same language session.
    """
    return f"""You are SQH (Secondary Query Handler).
Your only job: read the PQH analysis and return a precise JSON execution plan.

━━━ OUTPUT FORMAT (strict JSON, no markdown, no fences) ━━━
{{
  "acknowledge_answer": "...",
  "tasks": [...]
}}
CRITICAL:
- Output must start with "{{" and end with "}}".
- No explanation, no headings, no code fences.
- Strict JSON only — invalid output is rejected and retried.

━━━ TASK OBJECT SCHEMA ━━━
{{
  "task_id"          : "step_1",
  "tool"             : "exact_tool_name",
  "execution_target" : "client",
  "depends_on"       : [],
  "inputs"           : {{"arg_name": "value"}},
  "input_bindings"   : {{"arg_name": "$.step_1.data.field"}},
  "lifecycle_messages": {{
    "on_start"  : "...",
    "on_success": "...",
    "on_failure": "..."
  }},
  "control": {{
    "requires_approval": false,
    "on_failure": "abort"
  }}
}}

━━━ ACKNOWLEDGE ANSWER RULES ━━━
Language : {lang_label} (may sprinkle {secondary_lang} naturally).
Tone     : Warm, conversational — NOT robotic.
Tense    : In-progress only — action has started, not completed.
Length   : 1–2 short sentences max.
Vary the phrasing every time. Never repeat the same pattern.
  Examples: "Got it. Starting now." / "On it." / "Working on it." / "Under way."
Do NOT claim success or completion.

━━━ LIFECYCLE MESSAGE RULES ━━━
Language : {lang_label}.
on_start  : action just began (present tense)
on_success: action completed (past tense)
on_failure: action failed, what went wrong (brief)
Keep each under 10 words. Natural, not robotic.

━━━ TOOL USAGE RULES ━━━
- Use ONLY tools listed in the user message.
- Map every task to an exact tool name from the provided schemas.
- Multi-tool only when two distinct real-world actions are clearly needed.
- Never chain tools speculatively.

━━━ INPUT BINDING RULES (CRITICAL) ━━━
When task B depends on output from task A:
1. Add A's task_id to B's "depends_on" array.
2. Add a binding in B's "input_bindings": {{"param": "$.A_task_id.data.field"}}.
3. Do NOT hardcode paths or values that come from a previous task's output.
4. Common binding patterns:
   - file_create → file_open: {{"path": "$.step_1.data.file_path"}}
   - folder_create → file_create: {{"directory": "$.step_1.data.folder_path"}}
   - artifact_resolve → file_open: {{"path": "$.step_1.data.file_path"}}
   - web_search → summarize: {{"text": "$.step_1.data.results"}}
   - screenshot_capture → file_open: {{"path": "$.step_1.data.file_path"}}

━━━ ARTIFACT MEMORY RULES ━━━
- When the user references a previously created file, screenshot, or document
  (e.g. "open the file you created", "show me that screenshot", "open my notes"),
  check the RECENT ARTIFACTS section in the user message.
- Match by title/kind/content keywords to find the right artifact_id.
- Plan: artifact_resolve (server) → file_open (client) with input_bindings.
- Bind file_open.path to $.resolve_step.data.file_path
- Bind file_open.app to $.resolve_step.data.preferred_app
- Use query parameter in artifact_resolve for fuzzy matching.

━━━ SHELL AGENT RULES ━━━
- For complex tasks like "create a React app", "make a FastAPI server",
  "create a Python calculator" → use shell_agent with allow_network=true.
- shell_agent can handle multi-step project scaffolding, file creation,
  dependency installation, and build processes.
- Set allow_network=true for any task that might need npm, pip, npx, git, etc.

━━━ CONTENT GENERATE RULES ━━━
- For requests to write/create/generate text content (notes, articles, about-me, plans, essays, stories, lists) → use content_generate.
- NEVER put long content directly in file_create inputs.content — the token limit will truncate it.
- content_generate handles both generation AND file saving via output_path.
- If user wants a file, set output_path (e.g. "about_me.md", "notes.txt").
- If user specifies a line count, set min_lines accordingly.
- After content_generate, you can chain file_open to open the saved file."""


# ── Dynamic user message — changes per request ────────────────────────────────

def build_user_message(
    pqh_response: PQHResponse,
    user_preferences: Optional[Dict[str, Any]] = None,
    user_id: str = "guest",
) -> str:
    """
    Dynamic part — PQH context + tool schemas + preferences.
    Changes every SQH call, so it is never cached.
    """
    c = pqh_response.cognitive_state
    tool_names = pqh_response.requested_tool or []

    tool_schemas     = get_tools_schema(tool_names)
    tool_schemas_str = json.dumps(tool_schemas, indent=2)
    prefs_str        = json.dumps(user_preferences or {}, indent=2) if user_preferences else "None"

    # Inject recent artifact context for memory
    artifact_context = ""
    try:
        from app.agent.runtime.artifact_context_service import get_artifact_context_service
        artifact_context = get_artifact_context_service().get_recent_artifacts_context(
            user_id=user_id, limit=5, max_bytes=1500,
        )
    except Exception:
        pass
    artifact_block = ""
    if artifact_context:
        artifact_block = f"""

━━━ RECENT ARTIFACTS ━━━
{artifact_context}"""

    app_open_rules = ""
    artifact_open_rules = ""
    if "app_open" in tool_names:
        app_open_rules = """

APP_OPEN INTENT RULES:
- If the user explicitly says "in browser", "website", "web", or "online" → set inputs.destination = "browser".
- Plain "open X" → set inputs.destination = "auto".
- Local-only requests for installed apps/tools may set inputs.destination = "app" when needed.
- For plain app opens, set inputs.web_fallback_policy = "validate_then_ask" unless the user clearly does not want web fallback.
- Keep inputs.target focused on the thing to open, not the full sentence."""
    if "artifact_resolve" in tool_names and "file_open" in tool_names:
        artifact_open_rules = """

ARTIFACT OPEN RULES:
- For requests like "open the latest screenshot" or "open that saved txt file", plan TWO tasks:
  1. A server-side `artifact_resolve` task to locate the artifact and return `file_path` plus `preferred_app`.
  2. A client-side `file_open` task that depends on the resolve task.
- Bind `file_open.path` to `$.<resolve_task_id>.data.file_path`.
- Bind `file_open.app` to `$.<resolve_task_id>.data.preferred_app`.
- Prefer `kind="screenshot"` for screenshots/images.
- Prefer `kind="document"` plus `tool_name="file_create"` for latest/recent created files, notes, plans, or text documents.
- If the user names the content instead of the path, pass a short `query` to `artifact_resolve` (for example `"about me"` or `"weekly plan"`).
- Use `artifact_open` only when `file_open` is unavailable or the intent is explicitly to open it directly on the same runtime machine."""

    return f"""━━━ PQH ANALYSIS ━━━
User Query  : "{c.user_query}"
PQH Thought : "{c.thought_process}"
PQH Answer  : "{c.answer}"
Tools needed: {tool_names}

━━━ TOOL SCHEMAS ━━━
{tool_schemas_str}

━━━ SYSTEM PATHS ━━━
{_get_system_paths()}

━━━ USER PREFERENCES ━━━
{prefs_str}

PREFERENCE RULES:
- When opening an app, browser, or streaming service → check preferences first.
- Use first matching entry (e.g. preferences["movies"][0]).
- If empty → safe default (youtube for media, chrome for browser, notepad for text).
- Never invent a preference.
- When the user says "my desktop", "downloads", "documents" etc., use the paths from SYSTEM PATHS above. Do NOT ask the user for the path.
- "organize my desktop" → folder_organize with path = the desktop path from SYSTEM PATHS. NEVER ask which desktop.
- "organize downloads" → folder_organize with path = the downloads path from SYSTEM PATHS.
{app_open_rules}
{artifact_open_rules}
{artifact_block}
Generate the execution plan now."""


# ── Message builder ────────────────────────────────────────────────────────────

def build_messages(
    pqh_response: PQHResponse,
    user_lang: str = "en",
    user_preferences: Optional[Dict[str, Any]] = None,
    user_id: str = "guest",
) -> List[Dict[str, str]]:
    _LANG = {"hi": "Hindi", "ne": "Nepali", "en": "English"}
    lang_label     = _LANG.get(user_lang, "English")
    secondary_lang = "English" if user_lang != "en" else "Hindi"

    return [
        {"role": "system", "content": build_system_prompt(lang_label, secondary_lang)},
        {"role": "user",   "content": build_user_message(pqh_response, user_preferences, user_id=user_id)},
    ]
