"""PQH - Primary Query Handler
Pure Tool Decision Engine (~300-500 token static template)
"""
from typing import List, Dict
from app.agent.shared.registry.tool_index import get_tools_index


def build_prompt(current_query: str) -> str:
    available_tools = get_tools_index()

    tools_str = "\n".join(
        f"  {t['name']}: {t.get('description', '').strip()}"
        for t in available_tools
    )
    categories = sorted(set(t.get("category", "general") for t in available_tools))

    return f"""You are SPARK's Tool Decision Engine.

    AVAILABLE TOOLS ({len(available_tools)} | categories: {", ".join(categories)}):
    {tools_str}

    DECISION RULES:
    USE tool → query needs real-world action or live data (system control, files, OS, external services)
    NO tool  → query is purely cognitive (math, knowledge, code, chat, opinions)

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
        '"what is 15% of 340"    → {"request_id": "<uuid>", "cognitive_state": {"user_query": "what is 15% of 340", "thought_process": "english | tool:none | simple math calculation", "answer": "ok", "answer_english": "ok"}, "requested_tool": []}',
        '"hey what\'s up"         → {"request_id": "<uuid>", "cognitive_state": {"user_query": "hey what\'s up", "thought_process": "english | tool:none | casual greeting", "answer": "ok", "answer_english": "ok"}, "requested_tool": []}',
    ]

    return "\n".join(tool_examples + no_tool_examples)
if __name__ == "__main__":
    print(build_prompt("what is 15% of 340"))