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


def get_tools_schema(
    tool_names: List[str],
    connected_services: Optional[List[str]] = None,
) -> Dict[str, dict]:
    registry = get_tool_registry()
    schemas = {}
    _connected = set(connected_services or [])

    for name in tool_names:
        tool = registry.get_tool(name)
        if not tool:
            continue

        # Skip external (MCP) tools for services the user hasn't connected
        if tool.category == "external" and _connected:
            server = (tool.metadata or {}).get("server", "")
            if server and server not in _connected:
                continue

        # Skip email tools when Gmail isn't connected
        if _connected and "gmail" not in _connected and "email" in name:
            continue

        # Skip calendar tools when google_calendar isn't connected
        if _connected and "google_calendar" not in _connected and "calendar" in name:
            continue

        # Skip slack tools when slack isn't connected
        if _connected and "slack" not in _connected and name.startswith("slack_"):
            continue

        # Only serialize essential fields needed for planning to prevent token limit issues
        schemas[name] = {
            "description": tool.description,
            "execution_target": tool.execution_target,
            "params_schema": tool.params_schema,
        }
    return schemas


def _get_system_paths() -> str:
    """Return well-known OS paths so the LLM never needs to ask the user."""
    import os, sys
    from pathlib import Path

    home = Path.home()

    # On Windows, use shell folder API to get real paths (handles OneDrive redirection)
    if sys.platform == "win32":
        try:
            import ctypes.wintypes
            from ctypes import windll, create_unicode_buffer
            buf = create_unicode_buffer(260)
            # CSIDL constants: Desktop=0, Documents=5, Pictures=39, Music=13, Videos=14
            _get = windll.shell32.SHGetFolderPathW
            def _folder(csidl):
                b = create_unicode_buffer(260)
                _get(0, csidl, 0, 0, b)
                return b.value or ""
            paths = {
                "home": str(home),
                "desktop": _folder(0) or str(home / "Desktop"),
                "downloads": str(Path(os.environ.get("USERPROFILE", str(home))) / "Downloads"),
                "documents": _folder(5) or str(home / "Documents"),
                "pictures": _folder(39) or str(home / "Pictures"),
                "music": _folder(13) or str(home / "Music"),
                "videos": _folder(14) or str(home / "Videos"),
            }
        except Exception:
            paths = {k: str(home / k.capitalize()) for k in ("desktop", "downloads", "documents", "pictures", "music", "videos")}
            paths["home"] = str(home)
    else:
        paths = {
            "home": str(home),
            "desktop": str(home / "Desktop"),
            "downloads": str(home / "Downloads"),
            "documents": str(home / "Documents"),
            "pictures": str(home / "Pictures"),
            "music": str(home / "Music"),
            "videos": str(home / "Videos"),
        }

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
  "lifecycle_messages": {{"on_start":"...","on_success":"...","on_failure":"..."}},
  "control": {{"requires_approval": false, "on_failure": "abort"}}
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

━━━ MULTI-STEP CHAINING RULES ━━━
- "research X" → web_research(intent=research) → ai_summarize(context=$.step_1.data.text, mode="research")
- "make a file and open" → content_generate/file_create → file_open
- When user says "open it" after creating → chain file_open with input_bindings.
- ALWAYS include file_open as the last step when user says "open", "show", or "open in notepad"."""


# ── Dynamic user message — changes per request ────────────────────────────────

def build_user_message(
    pqh_response: PQHResponse,
    user_preferences: Optional[Dict[str, Any]] = None,
    user_id: str = "guest",
    connected_services: Optional[List[str]] = None,
) -> str:
    """
    Dynamic part — PQH context + tool schemas + preferences.
    Changes every SQH call, so it is never cached.

    If PQH returned a category, SQH sees ALL tools in that category
    and picks the exact tool(s) to use.
    """
    c = pqh_response.cognitive_state

    # Determine which tools to show SQH
    categories_list = pqh_response.category or []
    if isinstance(categories_list, str):
        categories_list = [categories_list]  # backward compat

    if categories_list:
        from app.prompts.tool_categories import get_tools_in_category
        tool_names = []
        for cat in categories_list:
            tool_names.extend(get_tools_in_category(cat))

        # Cross-category dependencies: some categories need tools from other
        # categories to build correct multi-step plans.
        #   entity_search needs current_location (web_knowledge) so SQH can
        #   plan "current_location → entity_search" for "near me" queries.
        _CROSS_CATEGORY_TOOLS: dict[str, list[str]] = {
            "entity_search": ["current_location"],
        }
        for cat in categories_list:
            for extra_tool in _CROSS_CATEGORY_TOOLS.get(cat, []):
                if extra_tool not in tool_names:
                    tool_names.append(extra_tool)

        tool_names = list(dict.fromkeys(tool_names))  # dedupe preserving order
    else:
        tool_names = []

    tool_schemas     = get_tools_schema(tool_names, connected_services=connected_services)
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

    # Category-specific rules — only injected when relevant tools are active
    tool_set = set(tool_names)
    category_rules_parts: list[str] = []

    if "app_open" in tool_set:
        category_rules_parts.append("""APP_OPEN: "in browser"→destination="browser", plain "open X"→destination="auto", set web_fallback_policy="validate_then_ask" for plain opens. inputs.target = the thing to open, not the full sentence.""")

    if "artifact_resolve" in tool_set and "file_open" in tool_set:
        category_rules_parts.append("""ARTIFACT OPEN: "open the file you created"→plan artifact_resolve(server)→file_open(client). Bind file_open.path to $.<resolve>.data.file_path, file_open.app to $.<resolve>.data.preferred_app. Use kind="screenshot" for images, kind="document" for text files.""")

    if "shell_agent" in tool_set:
        category_rules_parts.append("""SHELL AGENT: For complex multi-step tasks (create React app, FastAPI server)→use shell_agent with allow_network=true. NEVER use for WhatsApp calls/messages—use call_audio/message_send instead.""")

    if any(t in tool_set for t in ("call_audio", "call_video", "message_send", "email_send")):
        category_rules_parts.append("""COMMUNICATION: "call X"→call_audio. "video call"→call_video. "message X"/"text X"/"send to X"→message_send. "email X"/"mail X"→email_send. "WhatsApp" or unspecified→message_send/call_audio, NOT email.""")

    if "content_generate" in tool_set:
        category_rules_parts.append("""CONTENT GENERATE: For writing/creating text content→use content_generate (NOT file_create for long text). Set output_path for file saving, min_lines if user specifies line count. Chain file_open after if user wants to open it.""")

    if "file_create" in tool_set:
        category_rules_parts.append("""FILE_CREATE: inputs.content MUST be a plain text string (never list/dict). inputs.path MUST include file extension. Format structured data as readable text before passing.""")

    if "web_research" in tool_set:
        category_rules_parts.append("""WEB RESEARCH: Knowledge retrieval only. MUST set: formatted_queries (1-3 optimized search strings), intent.
Intents: factual_lookup | research.
- factual_lookup: short factual answers, snippets, weather, current state. Output: search snippets only (no scraping).
- research: deep dive, summaries, explanations. Output: scraped page content + concatenated text. ALWAYS chain ai_summarize after (bind context to $.step.data.text).
DO NOT use web_research for finding entities (hotels, restaurants, places, products, events, movies, colleges, flights, local services). Those go to entity_search.""")

    if "entity_search" in tool_set:
        category_rules_parts.append("""ENTITY SEARCH: Find structured entities (hotels, restaurants, places, etc). MUST set: query, intent.
Intents: hotel_search | restaurant_search | local_service | place_search | event_search | person_search | movie_search | college_search | flight_search | product_search.
entity_schema is auto-derived from intent; only set explicitly if overriding.
Intent mapping:
- "hotels/hostels/places to stay in X"            → hotel_search
- "buy X"/"price of X"/"X on amazon/flipkart"     → product_search
- "restaurants/where to eat in X"                  → restaurant_search
- "hospitals/gyms/pharmacies/clinics/banks/atms"   → local_service
- "who is X"/"X biography"/"tell me about Y"       → person_search   (person facts → use web_research instead)
- "X movie"/"best movies"/"what to watch tonight"  → movie_search
- "events in X"/"concerts in X"/"X festival"       → event_search
- "best colleges for X"/"X university"             → college_search
- "places to visit in X"/"things to do in Y"       → place_search
- "flights to X"/"X to Y flights"                  → flight_search
Geographic resolution — CRITICAL:
- "near me" / "nearby" / "around me" → plan current_location(client) FIRST, then entity_search(server) with input_bindings location=$.step_1.data.location_string, latitude=$.step_1.data.latitude, longitude=$.step_1.data.longitude. Bind ALL THREE. Latitude/longitude enable structured-provider retrieval (Google Places / Foursquare / OSM) and geo hard-filtering.
- "in <city>" / "around <place>" / "at <location>" → DO NOT plan current_location. The entity_search tool extracts the place name from the query and forward-geocodes it internally. Just pass the raw query through. Example: "hotels in Mumbai" → entity_search(intent=hotel_search, query="hotels in Mumbai"). The tool resolves Mumbai → coords → OSM by itself.
- No location mention at all → entity_search runs DDGS+LLM-extract fallback (lower quality). Avoid this when possible.
formatted_queries: only used by the DDGS fallback path. Set 1-3 short queries that include the resolved city name when relevant. No "site:" operators.
entity_search returns ranked entities directly — no chaining needed for the search itself. For follow-up actions (book, buy, play), chain browser_action with the entity as input.""")

    if "browser_action" in tool_set:
        category_rules_parts.append("""BROWSER ACTION: Transactional browser ops only — never search. MUST set: action.
Actions: open_url | play_media | book_hotel | buy_product | reserve_table | book_ticket.
Inputs:
- action: the verb (required, enum above)
- entity: the structured entity dict from a prior entity_search step (optional, recommended)
- url: explicit URL override (optional)
- title: for play_media when no entity is given
Typical chain: entity_search(intent=hotel_search) → browser_action(action=book_hotel, entity=$.step_1.data.entities[0]).
"play X movie"/"watch X" → action=play_media, title="X". Does not need entity_search first.
"book/buy/reserve that one" (referring to a prior search result) → action=book_hotel/buy_product/reserve_table with entity bound to the selected step output.""")

    category_rules_block = ""
    if category_rules_parts:
        category_rules_block = "\n\n━━━ CATEGORY-SPECIFIC RULES ━━━\n" + "\n".join(category_rules_parts)

    category_instruction = ""
    if categories_list:
        cats_str = ", ".join(categories_list)
        category_instruction = f"""
━━━ CATEGORIES: {cats_str} ━━━
PQH classified this request into: {cats_str}.
Pick the BEST tool(s) from the schemas below that match the user's exact intent.
"""

    return f"""{category_instruction}━━━ PQH ANALYSIS ━━━
User Query  : "{c.user_query}"
PQH Thought : "{c.thought_process}"
PQH Answer  : "{c.answer}"
Available tools: {tool_names}

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
{category_rules_block}
{artifact_block}
Generate the execution plan now."""


# ── Message builder ────────────────────────────────────────────────────────────

def build_messages(
    pqh_response: PQHResponse,
    user_lang: str = "en",
    user_preferences: Optional[Dict[str, Any]] = None,
    user_id: str = "guest",
    connected_services: Optional[List[str]] = None,
) -> List[Dict[str, str]]:
    _LANG = {"hi": "Hindi", "ne": "Nepali", "en": "English"}
    lang_label     = _LANG.get(user_lang, "English")
    secondary_lang = "English" if user_lang != "en" else "Hindi"

    return [
        {"role": "system", "content": build_system_prompt(lang_label, secondary_lang)},
        {"role": "user",   "content": build_user_message(pqh_response, user_preferences, user_id=user_id, connected_services=connected_services)},
    ]
