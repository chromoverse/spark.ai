"""
PQH Prompt — Tool Decision Engine

build_system_prompt() returns ONLY the static rules + tool registry.

Recent conversation and the user query are injected as real message
turns by chat_service._build_messages() — not as formatted text here.

This keeps the system prompt static so Groq can prefix-cache it.
The only thing that could bust the cache is a change to the tools
registry — which happens infrequently.
"""

from __future__ import annotations

from typing import List, Dict
from app.plugins.tools.tool_index_loader import get_tools_index


def build_system_prompt() -> str:
    """
    Static tool-decision system prompt.

    Does NOT include recent_context or the user query — those are
    injected as real message turns so the LLM attends to them properly.
    """
    available_tools = get_tools_index()

    tools_str = "\n".join(
        f"  {t['name']}: {t.get('description', '').strip()}"
        for t in available_tools
    )
    categories   = sorted(set(t.get("category", "general") for t in available_tools))
    semantic_rules = _build_semantic_tool_rules(available_tools)
    tool_examples  = _build_examples(available_tools)

    return f"""You are SPARK's Tool Decision Engine. Your only job: decide whether the user query needs a tool, and output strict JSON.

━━━ AVAILABLE TOOLS ({len(available_tools)} tools | categories: {", ".join(categories)}) ━━━
{tools_str}

━━━ CONVERSATION HISTORY ━━━
You will receive the recent conversation as real message turns above this system prompt.
Use them to resolve ambiguous references ("that one", "same app", "the model I mentioned").
If the answer or intent is clear from history → no tool needed.

━━━ DECISION GATES (top to bottom, stop at first match) ━━━

GATE 1 — HARD NO-TOOL (never needs a tool):
  • Jokes, banter, roasts, small talk, greetings
  • Math, logic, coding, general knowledge
  • Opinions, advice, definitions, explanations
  • Creative: poems, stories, rhymes, ideas
  • Anything answerable from conversation history
  ⚠️  NOT this gate: future events, predictions, current politics, election outcomes,
      "who will be next X", "latest news on Y" → those go to GATE 3 → web_research.

GATE 2 — RESOLVE FROM HISTORY FIRST:
  • Short or ambiguous query → check conversation turns above.
  • If history resolves it → answer directly, no tool.

GATE 3 — USE A TOOL only if:
  • Needs a real-world system action: open app, control OS, set alarm, manage files.
  • Needs live data: current weather, live prices, real-time news.
  • Needs a connected external service.
  • Needs web research: future predictions, political queries, "who will be next PM/president",
    election outcomes, current standings, "latest on X", anything requiring up-to-date info
    not answerable from general knowledge → web_research.

GATE 4 — MULTI-TOOL only if:
  • Two distinct real-world actions are clearly needed simultaneously.
  • Never chain tools speculatively.

⚠️  DEFAULT WHEN UNSURE → no tool. Always err toward answering directly.

━━━ WEB RESEARCH TOOL ━━━
web_research handles: future event predictions, political queries ("who will be next PM of Nepal"),
election results, current news, anything where the answer requires searching the web right now.
These are NOT general knowledge — do NOT answer them directly. Always invoke web_research.
Examples that must use web_research:
  "who will be next pm of nepal"     → web_research
  "who won the election"             → web_research
  "latest news on [topic]"           → web_research
  "what's happening with [politics]" → web_research
  "who is the current president of X"→ web_research

━━━ TOOL SEMANTICS ━━━
{semantic_rules}

━━━ OUTPUT FORMAT (strict JSON, no extra text) ━━━
{{
  "request_id": "<uuid>",
  "cognitive_state": {{
    "user_query": "<exact input>",
    "thought_process": "<lang> | tool:<name|none> | <5 word intent>",
    "answer": "ok",
    "answer_english": "ok"
  }},
  "requested_tool": ["<tool_name>"] or []
}}

━━━ EXAMPLES ━━━

No-tool cases:
  "tell me a joke"            → tool:none  | requested_tool: []
  "roast me"                  → tool:none  | requested_tool: []
  "what's 15% of 340"         → tool:none  | requested_tool: []
  "hey what's up"             → tool:none  | requested_tool: []
  "write me a haiku"          → tool:none  | requested_tool: []
  "explain machine learning"  → tool:none  | requested_tool: []
  "what did we talk about"    → tool:none  | requested_tool: []
  "which model did I mention" → tool:none  | requested_tool: []

web_research cases:
  "who will be next pm of nepal"      → tool:web_research | requested_tool: ["web_research"]
  "who won the recent election"       → tool:web_research | requested_tool: ["web_research"]
  "latest news on bitcoin"            → tool:web_research | requested_tool: ["web_research"]
  "current president of france"       → tool:web_research | requested_tool: ["web_research"]
  "what's happening in nepal politics"→ tool:web_research | requested_tool: ["web_research"]

{tool_examples}"""


def _build_semantic_tool_rules(tools: List[Dict]) -> str:
    tool_names = {t.get("name", "") for t in tools}
    rules: list[str] = []

    if "call_audio" in tool_names or "call_video" in tool_names:
        rules.append("  • Call intent (call/dial/ring/phone) → call_audio or call_video. Never message_send.")
    if "call_video" in tool_names:
        rules.append("  • Explicit video call request → call_video.")
    if "call_audio" in tool_names:
        rules.append("  • Call without video → call_audio.")
    if "message_send" in tool_names:
        rules.append("  • message_send is for text messages only.")
    if "web_research" in tool_names:
        rules.append("  • web_research is for future events, political queries, current news, anything needing live web search.")

    return "\n".join(rules) if rules else "  • No special semantic overrides."


def _build_examples(tools: List[Dict]) -> str:
    seen: set[str] = set()
    lines = ["Tool cases:"]
    for t in tools:
        cat = t.get("category", "general")
        if cat not in seen:
            seen.add(cat)
            name    = t["name"]
            desc    = t.get("description", "").strip().lower()[:35]
            trigger = name.replace("_", " ")
            lines.append(f'  "{trigger}" → tool:{name} | requested_tool: ["{name}"]  # {desc}')
        if len(lines) >= 6:
            break
    return "\n".join(lines)