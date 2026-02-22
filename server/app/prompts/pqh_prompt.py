"""
PQH - Primary Query Handler
Pure Tool Decision Engine — targets ~900-1000 tokens at runtime
"""
from typing import List, Dict, Optional
from app.agent.shared.registry.tool_index import get_tools_index


def _format_recent_context(recent_context: Optional[List[Dict]] = None) -> str:
    if not recent_context:
        return "  (none)"
    lines = []
    for msg in recent_context[-5:]:
        role = msg.get("role", "user")
        content = msg.get("content", "")[:120]
        lines.append(f"  {role}: {content}")
    return "\n".join(lines) if lines else "  (none)"


def build_prompt(current_query: str, recent_context: Optional[List[Dict]] = None) -> str:
    available_tools = get_tools_index()
    tools_str = "\n".join(
        f"  {t['name']}: {t.get('description', '').strip()}"
        for t in available_tools
    )
    categories = sorted(set(t.get("category", "general") for t in available_tools))
    recent_str = _format_recent_context(recent_context)

    return f"""You are SPARK's Tool Decision Engine. Your only job is to decide whether a user query needs a tool or not, and output a strict JSON decision.

━━━ AVAILABLE TOOLS ({len(available_tools)} tools | categories: {", ".join(categories)}) ━━━
{tools_str}

━━━ RECENT CONVERSATION ━━━
{recent_str}

━━━ DECISION GATES (work top to bottom, stop at first match) ━━━

GATE 1 — HARD NO-TOOL (these NEVER need a tool, no exceptions):
  • Jokes, banter, roasts, small talk, greetings
  • Math, logic, coding questions, general knowledge
  • Opinions, advice, definitions, explanations
  • Creative requests: poems, stories, rhymes, ideas
  • Anything recallable from RECENT CONVERSATION above

GATE 2 — RESOLVE FROM CONTEXT FIRST:
  • If the query is short or ambiguous, read RECENT CONVERSATION.
  • If context makes the intent clear → respond from context, no tool.
  • Example: user said "play something chill" earlier, now says "lo-fi" → play tool.
  • Example: user asked about a model earlier, now says "that one" → no tool, recall it.

GATE 3 — USE A TOOL only if:
  • Needs a real-world system action: open app, control OS, set alarm, manage files.
  • Needs genuinely live data: current weather, live prices, real-time news.
  • Needs to interact with a connected external service.

GATE 4 — MULTI-TOOL only if:
  • Query clearly needs two distinct real-world actions simultaneously.
  • Never chain tools speculatively or "just in case".

⚠️  DEFAULT WHEN UNSURE → no tool. Always err toward answering directly.

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

{_build_examples(available_tools)}
━━━ QUERY ━━━
{current_query}"""


def _build_examples(tools: List[Dict]) -> str:
    """One compact tool example per category, derived from registry."""
    seen_categories = set()
    lines = ["Tool cases:"]

    for t in tools:
        cat = t.get("category", "general")
        if cat not in seen_categories:
            seen_categories.add(cat)
            name = t["name"]
            desc = t.get("description", "").strip().lower()[:35]
            trigger = name.replace("_", " ")
            lines.append(f'  "{trigger}" → tool:{name} | requested_tool: ["{name}"]  # {desc}')
        if len(lines) >= 5:  # 4 tool examples max
            break

    return "\n".join(lines)


if __name__ == "__main__":
    print(build_prompt("tell me a joke"))
    print("---")
    print(build_prompt("what is 15% of 340"))