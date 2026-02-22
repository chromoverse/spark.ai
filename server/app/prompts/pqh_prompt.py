"""
PQH - Primary Query Handler
Pure Tool Decision Engine (~300-500 token static template)
"""
from typing import List, Dict, Optional
from app.agent.shared.registry.tool_index import get_tools_index


def _format_recent_context(recent_context: Optional[List[Dict]] = None) -> str:
    """Format recent messages compactly for PQH context resolution"""
    if not recent_context:
        return "  (none)"
    lines = []
    for msg in recent_context[-5:]:  # last 5 max
        role = msg.get("role", "user")
        content = msg.get("content", "")[:120]  # truncate long messages
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

    return f"""You are SPARK's Tool Decision Engine.

AVAILABLE TOOLS ({len(available_tools)} | categories: {", ".join(categories)}):
{tools_str}

RECENT CONVERSATION (use to resolve ambiguous references):
{recent_str}

DECISION RULES:
Before reaching for any tool, ask yourself in order:

  1. RECALL — Is the user referencing something from this conversation,
     their preferences, past requests, or something already known?
     If yes → no tool. The answer lives in the stream.

  2. COGNITION — Is this math, reasoning, code, opinion, or general knowledge?
     If yes → no tool. Think it through.

  3. TOOL — Does this genuinely require a real-world action or live external data
     that cannot come from memory or reasoning alone?
     If yes → use the minimal tool(s) needed.

  4. CONTEXT RESOLUTION — If the current query is short or ambiguous (e.g. just a name
     or a single word), look at RECENT CONVERSATION to understand the user's intent.
     Example: if user previously said "I want to watch movies" and now says "Game of Thrones",
     the intent is to play/search for that movie — use the appropriate tool.

USE tool  → query needs real-world action or live data (system control, files, OS, external services)
NO tool   → query is recall, cognitive, conversational, or already answered in context
MULTI-TOOL: only if query clearly needs sequential/parallel actions.

OUTPUT strict JSON only:
{{
  "request_id": "<uuid>",
  "cognitive_state": {{
    "user_query": "<exact input>",
    "thought_process": "<lang> | tool:<name|none> | intent:<5 words>",
    "answer": "ok",
    "answer_english": "ok"
  }},
  "requested_tool": ["<tool_name>"] OR []
}}

{_build_examples(available_tools)}
QUERY: {current_query}"""


def _build_examples(tools: List[Dict]) -> str:
    """
    Dynamically generate examples from the actual tool registry.
    Picks one tool per category for tool examples, plus static no-tool cases.
    Never hardcodes tool names — derives them from registry.
    """
    seen_categories = set()
    tool_examples = []

    for t in tools:
        cat = t.get("category", "general")
        if cat not in seen_categories:
            seen_categories.add(cat)
            name = t["name"]
            desc = t.get("description", "").strip().lower()
            trigger = f"use {name.replace('_', ' ')}"
            tool_examples.append(
                f'"{trigger}" → {{"request_id": "<uuid>", "cognitive_state": {{"user_query": "{trigger}", '
                f'"thought_process": "english | tool:{name} | {desc[:30]}", '
                f'"answer": "ok", "answer_english": "ok"}}, "requested_tool": ["{name}"]}}'
            )
        if len(tool_examples) >= 3:
            break

    no_tool_examples = [
        '"what is 15% of 340"        → {"request_id": "<uuid>", "cognitive_state": {"user_query": "what is 15% of 340", "thought_process": "english | tool:none | simple math calculation", "answer": "ok", "answer_english": "ok"}, "requested_tool": []}',
        '"hey what\'s up"             → {"request_id": "<uuid>", "cognitive_state": {"user_query": "hey what\'s up", "thought_process": "english | tool:none | casual greeting", "answer": "ok", "answer_english": "ok"}, "requested_tool": []}',
        '"what model did we discuss"  → {"request_id": "<uuid>", "cognitive_state": {"user_query": "what model did we discuss", "thought_process": "english | tool:none | recall from conversation", "answer": "ok", "answer_english": "ok"}, "requested_tool": []}',
    ]

    return "\n".join(tool_examples + no_tool_examples)


if __name__ == "__main__":
    print(build_prompt("what is 15% of 340"))