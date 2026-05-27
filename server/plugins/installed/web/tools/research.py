"""
web_research — knowledge retrieval.

Responsibility
──────────────
Gather raw web information for the downstream summarizer. Two intents:

  factual_lookup  → snippets only (no scraping, no LLM)
  research        → scraped page content + concatenated text context
                    ready to feed into ``ai_summarize``

Architectural split
───────────────────
Entity discovery (hotels, restaurants, hospitals, attractions, products,
events, movies, colleges, flights, …) lives in ``entity_search``. That
tool owns the structured-provider chain, geo resolution, ranking, and
the LLM-extract fallback. ``web_research`` no longer touches any of it.

Use ``web_research`` for:
  • "what is X" / "who is Y" / "summary of Z"          → research
  • "current weather", "news today", "fact about X"    → factual_lookup
  • Anything that produces *prose* or *snippets* for the LLM to consume.

Use ``entity_search`` for:
  • "hotels in X" / "restaurants near me" / "places to visit in Y"
  • Anything that should produce a *list of structured entities*.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from app.plugins.tools.tool_base import BaseTool, ToolOutput

from . import _shared

_log = logging.getLogger(__name__)
_emit = _shared.make_emitter("web_research")


_VALID_INTENTS = {"factual_lookup", "research"}

# Overall wall-clock cap for the entire web_research call.
_TOTAL_TIMEOUT_S = 75.0


class WebResearchTool(BaseTool):
    """Knowledge-retrieval tool.

    Inputs:
      query              (string, required)
      formatted_queries  (array, optional)
      intent             (string, optional, default 'research')
      max_results        (integer, optional)
      max_chars          (integer, optional)

    Outputs:
      factual_lookup → {result_type:"snippets",        snippets:[…], sources:[…]}
      research       → {result_type:"scraped_content", scraped_content:[…],
                        text:"…", sources:[…]}
    """

    TOOL_DESCRIPTION = (
        "Gather raw web information for the LLM summarizer. Returns search "
        "snippets (factual_lookup) or scraped page content (research). "
        "Does NOT produce prose — chain ai_summarize after for an answer. "
        "Does NOT find entities — use entity_search for hotels, restaurants, "
        "places, events, products, etc."
    )
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA: Dict[str, Any] = {
        "query": {"type": "string", "required": True},
        "formatted_queries": {"type": "array", "required": False},
        "intent": {
            "type": "string",
            "required": False,
            "default": "research",
            "enum": list(_VALID_INTENTS),
            "description": "factual_lookup (snippets) | research (scraped pages)",
        },
        "max_results": {"type": "integer", "required": False, "default": 5},
        "max_chars": {"type": "integer", "required": False, "default": 5000},
    }
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {
            "intent":          {"type": "string"},
            "result_type":     {"type": "string", "description": "snippets | scraped_content"},
            "sources":         {"type": "array"},
            "snippets":        {"type": "array",  "optional": True, "description": "factual_lookup only"},
            "scraped_content": {"type": "array",  "optional": True, "description": "research only"},
            "text":            {"type": "string", "optional": True, "description": "research only — ready for ai_summarize"},
        },
        "error": {"type": "string"},
    }
    EXAMPLES = [
        {"user_utterance": "research nepal politics"},
        {"user_utterance": "what is the capital of japan"},
    ]
    SEMANTIC_TAGS = ["web", "research", "knowledge", "summarize"]
    TOOL_CATEGORY = "web_knowledge"
    METADATA: Dict[str, Any] = {"summary_tts": "intent_search"}

    def get_tool_name(self) -> str:
        return "web_research"

    # ── Entry point ──────────────────────────────────────────────────────────

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Wall-clock guard wrapper. On timeout we return empty rather
        than raising so the failure classifier can treat it as recoverable."""
        try:
            return await asyncio.wait_for(self._execute_inner(inputs), timeout=_TOTAL_TIMEOUT_S)
        except asyncio.TimeoutError:
            user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "")
            task_id = str(inputs.get("_task_id") or "")
            await _emit(user_id, task_id, "timeout",
                        f"web_research timed out after {_TOTAL_TIMEOUT_S:.0f}s")
            _log.warning("web_research total timeout (%.0fs) hit for query=%r",
                         _TOTAL_TIMEOUT_S, inputs.get("query"))
            return ToolOutput(
                success=False, data={},
                error=f"web_research exceeded {_TOTAL_TIMEOUT_S:.0f}s wall-clock budget",
            )

    async def _execute_inner(self, inputs: Dict[str, Any]) -> ToolOutput:
        query = self.get_input(inputs, "query", "").strip()
        if not query:
            return ToolOutput(success=False, data={}, error="Query is required")

        intent = str(self.get_input(inputs, "intent", "research") or "research").lower()
        if intent not in _VALID_INTENTS:
            # Defensive: if SQH sends an entity intent here, surface a clear
            # error so the orchestrator can replan into entity_search instead
            # of silently degrading to a generic research run.
            return ToolOutput(
                success=False, data={},
                error=(
                    f"web_research only handles factual_lookup/research. "
                    f"Got {intent!r}; route entity intents to entity_search."
                ),
            )

        formatted_queries: List[str] = self.get_input(inputs, "formatted_queries", []) or []
        max_results = int(self.get_input(inputs, "max_results", 5) or 5)
        max_chars = int(self.get_input(inputs, "max_chars", 5000) or 5000)

        search_queries = formatted_queries if formatted_queries else [query]

        user_id: str = str(inputs.get("_user_id") or inputs.get("user_id") or "")
        task_id: str = str(inputs.get("_task_id") or "")

        await _emit(
            user_id, task_id, "start",
            f"Researching: {query[:80]}",
            intent=intent, query_count=len(search_queries),
        )

        if intent == "factual_lookup":
            return await self._handle_factual(query, search_queries, max_results, user_id, task_id)
        return await self._handle_research(query, search_queries, max_results, max_chars, user_id, task_id)

    # ── factual_lookup ───────────────────────────────────────────────────────

    async def _handle_factual(
        self,
        query: str,
        search_queries: List[str],
        max_results: int,
        user_id: str,
        task_id: str,
    ) -> ToolOutput:
        """Search snippets only — no scraping, no LLM. Pure data."""
        all_results, sources = await _shared.multi_search(
            search_queries, max_results,
            tool_name="web_research", user_id=user_id, task_id=task_id,
        )
        await _emit(user_id, task_id, "search_complete",
                    f"Found {len(all_results)} snippets", count=len(all_results))

        snippets = [
            {
                "title": r.get("title", ""),
                "snippet": r.get("snippet", ""),
                "url": r.get("url", ""),
            }
            for r in all_results[:max_results]
            if r.get("snippet")
        ]
        return ToolOutput(
            success=True,
            data={
                "intent": "factual_lookup",
                "result_type": "snippets",
                "snippets": snippets,
                "sources": sources,
            },
        )

    # ── research (raw scraped pages) ────────────────────────────────────────

    async def _handle_research(
        self,
        query: str,
        search_queries: List[str],
        max_results: int,
        max_chars: int,
        user_id: str,
        task_id: str,
    ) -> ToolOutput:
        await _emit(user_id, task_id, "searching", f"Searching {len(search_queries)} queries")
        all_results, sources = await _shared.multi_search(
            search_queries, max_results,
            tool_name="web_research", user_id=user_id, task_id=task_id,
        )
        await _emit(user_id, task_id, "search_complete",
                    f"Found {len(all_results)} results", count=len(all_results))

        if not all_results:
            return ToolOutput(
                success=True,
                data={
                    "intent": "research",
                    "result_type": "scraped_content",
                    "scraped_content": [],
                    "text": "",
                    "sources": [],
                },
            )

        urls = [r["url"] for r in all_results]
        await _emit(user_id, task_id, "scraping",
                    f"Scraping {min(len(urls), max_results)} pages",
                    url_count=min(len(urls), max_results))
        scraped = await _shared.scrape_urls(urls, max_results, max_chars)

        pages = [
            {
                "url": item.get("url", ""),
                "title": item.get("title", ""),
                "text": (item.get("text") or "")[:max_chars],
            }
            for item in scraped
            if item.get("text")
        ]
        # Pre-built concatenated context so ai_summarize can bind
        # $.<step>.data.text directly without rebuilding the corpus.
        text_context = "\n\n---\n\n".join(
            f"Source: {p['url']}\nTitle: {p['title']}\nContent:\n{p['text']}"
            for p in pages
        )

        await _emit(user_id, task_id, "complete",
                    f"Scraped {len(pages)} pages", count=len(pages))

        return ToolOutput(
            success=True,
            data={
                "intent": "research",
                "result_type": "scraped_content",
                "scraped_content": pages,
                "text": text_context,
                "sources": sources,
            },
        )


__all__ = ["WebResearchTool"]
