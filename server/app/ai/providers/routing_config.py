"""
Routing Config — Static use-case → provider chain mapping.

Zero overhead: pure dict lookup, no LLM call needed for routing.
Each use-case maps to an ordered list of (provider, model) tuples.
The router tries them in order; if one fails/exhausted, falls to next.
"""

from typing import Dict, List, Tuple

# Use-case identifiers (used as dict keys throughout the system)
USE_CASE_STREAMING = "streaming"        # PQH / SQH / Streaming chat
USE_CASE_REASONING = "reasoning"        # Deep thinking / complex tasks
USE_CASE_LIGHTWEIGHT = "lightweight"    # folder_organize, task speech
USE_CASE_CONTENT = "content_generate"   # Long-form content (4K-8K tokens)
USE_CASE_SUMMARIZE = "summarize"        # ai_summarize (async, tolerant)
USE_CASE_EXTRACT = "entity_extract"     # Structured entity extraction from web content

# Provider chain per use-case: list of (provider_name, model)
# Order = priority. First available provider wins.
ROUTING_TABLE: Dict[str, List[Tuple[str, str]]] = {
    USE_CASE_STREAMING: [
        ("cerebras", "gpt-oss-120b"),
        ("groq", "llama-3.3-70b-versatile"),
        ("gemini", "gemini-2.5-flash"),
    ],
    USE_CASE_REASONING: [
        ("cerebras", "qwen-3-235b-a22b-instruct-2507"),
        ("sambanova", "DeepSeek-V3.2"),
    ],
    USE_CASE_LIGHTWEIGHT: [
        ("groq", "llama-3.1-8b-instant"),
        ("cerebras", "llama3.1-8b"),
    ],
    USE_CASE_CONTENT: [
        ("sambanova", "DeepSeek-V3.1"),
        ("gemini", "gemini-2.5-flash"),
    ],
    USE_CASE_SUMMARIZE: [
        ("mistral", "mistral-small-latest"),
        ("groq", "llama-3.3-70b-versatile"),
    ],
    USE_CASE_EXTRACT: [
        ("groq", "llama-3.3-70b-versatile"),
        ("mistral", "mistral-small-latest"),
        ("cerebras", "gpt-oss-120b"),
    ],
}

# Universal fallback — tried if ALL providers for a use-case fail
UNIVERSAL_FALLBACK: List[Tuple[str, str]] = [
    ("openrouter", "deepseek/deepseek-r1-0528"),
    ("gemini", "gemini-2.5-flash"),
    ("groq", "llama-3.3-70b-versatile"),
    ("cerebras", "gpt-oss-120b"),
    ("sambanova", "DeepSeek-V3.2"),
    ("mistral", "mistral-small-latest"),
]
