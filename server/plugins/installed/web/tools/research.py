"""
web_research — pure data-gathering tool.

Design principle: this tool ONLY gathers raw web data shaped for the
caller's intent. It does NOT summarize, format, or synthesize prose.
Downstream tools (ai_summarize, content_generate, etc.) handle that
when SQH chains them together.

Output shape per intent
───────────────────────
factual_lookup   → {result_type:"snippets",         snippets:[…],         sources:[…]}
research         → {result_type:"scraped_content",  scraped_content:[…],  text:"…",  sources:[…]}
hotel_search     ┐
product_search   ├ {result_type:"entities", entities:[…], sources:[…], actions:[…]}
restaurant_search│
local_service    ┘

Common to every output: ``intent``, ``result_type``, ``sources``.
All variant fields are declared optional in OUTPUT_SCHEMA so the
BaseTool contract validator does not warn for non-applicable fields.

Live progress
─────────────
While running, the tool emits ``tool_progress`` events via the kernel
log stream so the UI can show searching → scraping → extracting → ranking
steps in real time. Searching and scraping run in parallel via asyncio.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus, urlparse

from app.plugins.tools.tool_base import BaseTool, ToolOutput
from .scrape import WebScrapeTool
from .search import WebSearchTool

_log = logging.getLogger(__name__)


_VALID_INTENTS = {
    "factual_lookup",
    "research",
    "hotel_search",
    "product_search",
    "restaurant_search",
    "local_service",
    "person_search",
    "movie_search",
    "event_search",
    "college_search",
    "place_search",
    "flight_search",
}

_ENTITY_INTENT_MAP = {
    "hotel_search": "hotel",
    "product_search": "product",
    "restaurant_search": "restaurant",
    "local_service": "local_business",
    "person_search": "person",
    "movie_search": "movie",
    "event_search": "event",
    "college_search": "college",
    "place_search": "place",
    "flight_search": "flight",
}

_TYPE_LABELS = {
    "hotel": "Hotel",
    "product": "Product",
    "restaurant": "Restaurant",
    "local_business": "Local Business",
    "person": "Person",
    "movie": "Movie / Show",
    "event": "Event",
    "college": "College",
    "place": "Place",
    "flight": "Flight",
}

# Hard caps so this tool can never block the server indefinitely.
# - PER_QUERY_S: outer timeout for one search query. Even if DDGS internally
#   hangs across all its fallback engines, asyncio.wait_for will abandon the
#   coroutine and free the dedicated executor thread.
# - MAX_PARALLEL: ceiling on concurrent search calls so we don't saturate the
#   default ThreadPoolExecutor (max ~32 workers) and starve other async work
#   such as socket.io heartbeats, STT pipelines, or unrelated tools.
# - MAX_QUERIES: defense in depth against SQH or fallback templates producing
#   too many queries. Five is plenty given parallel execution.
# - SCRAPE_S: wall-clock cap for the whole scrape phase. scrape.py has its
#   own per-URL bounds (httpx 15s, semaphore 5) but the Playwright fallback
#   path can stall on Windows, so we add a belt-and-suspenders ceiling.
# - EXTRACT_S: wall-clock cap for the LLM entity-extraction call. Without
#   this a hung Groq/LLM provider could eat the entire tool budget.
# - TOTAL_S: overall wall-clock cap for the entire web_research call.
_PER_QUERY_TIMEOUT_S = 12.0
_MAX_PARALLEL_SEARCHES = 2
_MAX_QUERIES = 3
_SCRAPE_TIMEOUT_S = 35.0
_EXTRACT_TIMEOUT_S = 20.0
_IMAGE_ENRICH_TIMEOUT_S = 25.0   # budget for post-extraction nodriver image enrichment
_TOTAL_TIMEOUT_S = 75.0

# Site-scoped fallback queries appended when an entity search returns thin
# results. These are scrape-friendly (no bot walls) and are intentionally
# kept here (NOT in SQH) so SQH plans don't duplicate them.
_SCRAPEABLE_SITE_QUERIES: Dict[str, List[str]] = {
    "hotel_search": [
        "site:budgetyourtrip.com cheap hotels {location}",
        "site:hostelworld.com {location} budget hostel hotel",
        "{location} budget hotel price per night oyorooms OR hostelworld",
    ],
    "restaurant_search": [
        "{location} best restaurants menu price zomato OR yelp",
    ],
    "local_service": [
        "{location} {query} near me reviews",
    ],
    "person_search": [
        "{query} biography wikipedia",
        "{query} imdb OR linkedin profile",
    ],
    "movie_search": [
        "site:imdb.com {query}",
        "{query} movie review rating cast rotten tomatoes OR metacritic",
    ],
    "event_search": [
        "{location} events {query} 2026",
        "{query} tickets {location} bookmyshow OR eventbrite",
    ],
    "college_search": [
        "{query} college university ranking admission fees {location}",
        "site:collegedunia.com OR site:shiksha.com {query}",
    ],
    "place_search": [
        "{query} tourist attraction things to do {location}",
        "site:tripadvisor.com {query} {location} attractions",
    ],
    "flight_search": [
        "{query} flight price schedule airline",
        "{query} flights skyscanner OR google flights",
    ],
}


# ── Live progress emitter ────────────────────────────────────────────────────

async def _emit(user_id: str, task_id: str, stage: str, message: str, **extra: Any) -> None:
    """Emit a tool_progress event to the user's socket. Best-effort, never raises."""
    if not user_id:
        return
    try:
        from app.socket.log_stream import emit_spark_log
        await emit_spark_log(
            user_id,
            "tool_progress",
            task_id=task_id,
            tool_name="web_research",
            payload={"stage": stage, "message": message, **extra},
        )
    except Exception:  # pragma: no cover — never let UI emit break the tool
        pass


class WebResearchTool(BaseTool):
    """
    Intent-aware web data gatherer. Pure: no summarization, no synthesis.

    Inputs (set by SQH):
      query              (string, required)
      formatted_queries  (array, optional)   — search strings
      intent             (string, optional)  — see _VALID_INTENTS
      entity_schema      (string, optional)  — hotel|product|restaurant|local_business
      location           (string, optional)  — city/region from current_location binding
      max_results        (integer, optional)
      max_chars          (integer, optional)

    Output: see module docstring.
    """

    TOOL_DESCRIPTION = (
        "Gathers raw web data for a query. Returns search snippets, scraped "
        "page content, or structured entities (hotels, products, restaurants, "
        "local businesses, people, movies/shows, events, colleges, places, flights) "
        "depending on intent. Does NOT summarize — chain ai_summarize after for prose answers."
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
        },
        "entity_schema": {
            "type": "string",
            "required": False,
            "enum": [
                "hotel", "product", "restaurant", "local_business",
                "person", "movie", "event", "college", "place", "flight",
            ],
        },
        "location": {
            "type": "string",
            "required": False,
            "description": "City/region from current_location binding (e.g. 'Mumbai, Maharashtra'). Replaces 'near me' in formatted_queries.",
        },
        "max_results": {"type": "integer", "required": False, "default": 5},
        "max_chars": {"type": "integer", "required": False, "default": 5000},
    }
    # Output schema. Only `intent`, `result_type`, `sources` are guaranteed
    # for every call. The rest are intent-specific and marked optional so
    # the BaseTool contract validator does not warn for fields that don't
    # apply to the current intent.
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {
            "intent":           {"type": "string"},
            "result_type":      {"type": "string", "description": "snippets | scraped_content | entities"},
            "sources":          {"type": "array"},
            "snippets":         {"type": "array",  "optional": True, "description": "factual_lookup only"},
            "scraped_content":  {"type": "array",  "optional": True, "description": "research only"},
            "text":             {"type": "string", "optional": True, "description": "research only — concatenated context ready to feed into ai_summarize"},
            "entities":         {"type": "array",  "optional": True, "description": "*_search / local_service"},
            "actions":          {"type": "array",  "optional": True, "description": "*_search / local_service"},
        },
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "web research"}]
    SEMANTIC_TAGS = ["web", "web", "research"]
    TOOL_CATEGORY = "web_knowledge"
    METADATA: Dict[str, Any] = {"summary_tts": "intent_search"}  # speak only for search intents

    def get_tool_name(self) -> str:
        return "web_research"

    # ── Entry point ──────────────────────────────────────────────────────────

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Top-level entry. Wraps the real work in a wall-clock timeout so
        this tool can never block the event loop indefinitely (DDGS hangs,
        scrape hangs, runaway LLM calls, etc.). On timeout we return a
        graceful empty result rather than raising — failure-classifier
        treats this as a recoverable failure that SQH can replan."""
        try:
            return await asyncio.wait_for(self._execute_inner(inputs), timeout=_TOTAL_TIMEOUT_S)
        except asyncio.TimeoutError:
            user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "")
            task_id = str(inputs.get("_task_id") or "")
            await _emit(
                user_id, task_id, "timeout",
                f"web_research timed out after {_TOTAL_TIMEOUT_S:.0f}s",
            )
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
            intent = "research"

        formatted_queries: List[str] = self.get_input(inputs, "formatted_queries", []) or []
        entity_schema: str = self.get_input(inputs, "entity_schema", "") or ""
        location: str = str(self.get_input(inputs, "location", "") or "").strip()
        max_results = int(self.get_input(inputs, "max_results", 5) or 5)
        max_chars = int(self.get_input(inputs, "max_chars", 5000) or 5000)

        # Auto-derive entity_schema from intent if not explicitly passed
        if not entity_schema and intent in _ENTITY_INTENT_MAP:
            entity_schema = _ENTITY_INTENT_MAP[intent]

        # Resolve "near me" → actual location when binding is provided
        if location:
            query = _inject_location(query, location)
            formatted_queries = [_inject_location(q, location) for q in formatted_queries]

        search_queries = formatted_queries if formatted_queries else [query]

        user_id: str = str(inputs.get("_user_id") or inputs.get("user_id") or "")
        task_id: str = str(inputs.get("_task_id") or "")

        await _emit(
            user_id, task_id, "start",
            f"Researching: {query[:80]}",
            intent=intent, query_count=len(search_queries),
        )

        if intent == "factual_lookup":
            return await self._handle_factual(
                query, search_queries, max_results, user_id, task_id,
            )
        if intent in _ENTITY_INTENT_MAP:
            return await self._handle_entity(
                query, search_queries, entity_schema,
                max_results, max_chars, location,
                user_id, task_id,
            )
        return await self._handle_research(
            query, search_queries, max_results, max_chars, user_id, task_id,
        )

    # ── Route: factual_lookup ────────────────────────────────────────────────

    async def _handle_factual(
        self,
        query: str,
        search_queries: List[str],
        max_results: int,
        user_id: str,
        task_id: str,
    ) -> ToolOutput:
        """Search snippets only — no scraping, no LLM. Pure data."""
        all_results, sources = await self._multi_search(
            search_queries, max_results, user_id, task_id,
        )
        await _emit(user_id, task_id, "search_complete", f"Found {len(all_results)} snippets", count=len(all_results))

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
            data=_build_response(
                "factual_lookup", "snippets",
                snippets=snippets, sources=sources,
            ),
        )

    # ── Route: entity search (hotel / product / restaurant / local_service) ──

    async def _handle_entity(
        self,
        query: str,
        search_queries: List[str],
        entity_schema: str,
        max_results: int,
        max_chars: int,
        location: str,
        user_id: str,
        task_id: str,
    ) -> ToolOutput:
        intent_key = next(
            (k for k, v in _ENTITY_INTENT_MAP.items() if v == entity_schema),
            entity_schema + "_search",
        )

        # ── Fast path: OpenCLI browser agent ────────────────────────────────
        # For any entity intent with registered site adapters, try the
        # Playwright browser agent first — it navigates live sites, fills
        # search forms, and extracts structured DOM nodes directly.
        # No search queries, no LLM, no scraping.
        # Falls back silently to the standard search→scrape→extract path below.
        from .browser_agent import BrowserAgent, SITE_REGISTRY as _BA_REGISTRY
        if intent_key in _BA_REGISTRY:
            _intent_label = intent_key.replace("_", " ")
            await _emit(
                user_id, task_id, "browser_agent",
                f"Opening live browser agent for {_intent_label}…",
            )
            ba_entities, ba_sources = await BrowserAgent.run(
                intent=intent_key,
                location=location,
                query=query,
                max_results=max_results,
                user_id=user_id,
                task_id=task_id,
            )
            if ba_entities:
                from .ranker import rank_entities
                ranked = rank_entities(ba_entities, entity_schema, query)
                _enrich_maps_urls(ranked, location)
                _enrich_type_labels(ranked, entity_schema)
                # Enrich images for entities that the browser adapter couldn't capture
                await _enrich_images_nodriver(ranked, top_n=5, user_id=user_id, task_id=task_id)
                await _emit(
                    user_id, task_id, "complete",
                    f"Done — {len(ranked[:15])} results via browser agent",
                    count=len(ranked[:15]),
                )
                actions: List[Dict[str, Any]] = _build_actions(entity_schema)
                return ToolOutput(
                    success=True,
                    data=_build_response(
                        intent_key, "entities",
                        entities=ranked[:15],
                        sources=ba_sources,
                        actions=actions,
                    ),
                )
            await _emit(
                user_id, task_id, "browser_fallback",
                "Browser agent returned no results — falling back to web search",
            )
        # ── End fast path ────────────────────────────────────────────────────

        # Build site-scoped fallback queries (kept here, not in SQH)
        fallback_templates = _SCRAPEABLE_SITE_QUERIES.get(intent_key, [])
        loc = location or query
        fallback_queries = [t.format(location=loc, query=query) for t in fallback_templates]
        all_search_queries = list(dict.fromkeys(search_queries + fallback_queries))

        # 1. Search (parallel across queries)
        await _emit(
            user_id, task_id, "searching",
            f"Searching {len(all_search_queries)} queries in parallel",
            queries=all_search_queries[:6],
        )
        all_results, sources = await self._multi_search(
            all_search_queries, max_results, user_id, task_id,
        )
        await _emit(
            user_id, task_id, "search_complete",
            f"Found {len(all_results)} unique results",
            count=len(all_results),
        )

        if not all_results:
            return ToolOutput(
                success=True,
                data=_build_response(intent_key, "entities", entities=[], sources=[]),
            )

        # 2. Scrape — skip ad-redirect URLs
        urls = [r["url"] for r in all_results if not _is_ad_redirect(r["url"])]
        if not urls:
            urls = [r["url"] for r in all_results]  # fallback: try everything
        await _emit(
            user_id, task_id, "scraping",
            f"Scraping {min(len(urls), max_results)} pages",
            url_count=min(len(urls), max_results),
            urls=[{"url": u, "domain": urlparse(u).netloc.replace("www.", "")} for u in urls[:max_results]],
        )
        # Entity pages are often JS-rendered — use nodriver so we capture real images
        scraped = await self._scrape_urls(urls, max_results, max_chars, use_nodriver=True)
        scraped_with_text = [s for s in scraped if s.get("text")]
        await _emit(
            user_id, task_id, "scrape_complete",
            f"Scraped {len(scraped_with_text)} pages",
            count=len(scraped_with_text),
        )

        # Fallback: if scraping yielded nothing, use search snippets as context
        if not scraped_with_text:
            scraped_with_text = [
                {
                    "url": r.get("url", ""),
                    "title": r.get("title", ""),
                    "text": f"{r.get('title', '')}. {r.get('snippet', '')}",
                }
                for r in all_results
                if r.get("snippet")
            ]

        # 3. Entity extract (1 LLM call). Bounded so a hung LLM provider
        #    cannot eat the entire tool budget — on timeout we degrade to
        #    "no entities" rather than failing the whole call.
        await _emit(user_id, task_id, "extracting", f"Extracting {entity_schema} entities")
        from .entity_extractor import extract_entities
        try:
            entities = await asyncio.wait_for(
                extract_entities(scraped_with_text, entity_schema, query, location),
                timeout=_EXTRACT_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            _log.warning(
                "entity extraction timed out (>%.0fs) for %s",
                _EXTRACT_TIMEOUT_S, entity_schema,
            )
            await _emit(
                user_id, task_id, "extract_timeout",
                f"⏱  Entity extraction timed out after {_EXTRACT_TIMEOUT_S:.0f}s",
            )
            entities = []
        await _emit(
            user_id, task_id, "extract_complete",
            f"Extracted {len(entities)} entities",
            count=len(entities),
        )

        # 4. Rank
        from .ranker import rank_entities
        ranked = rank_entities(entities, entity_schema, query)

        # 5. Image enrichment — pull from scraped HTML first, then nodriver for gaps
        _enrich_images_from_scraped(ranked, scraped)
        await _enrich_images_nodriver(ranked, top_n=5, user_id=user_id, task_id=task_id)

        # 6. Map links — pure string construction, no API calls
        _enrich_maps_urls(ranked, location)

        # 7. Type labels for UI display
        _enrich_type_labels(ranked, entity_schema)

        # Append scraped pages as additional sources
        for item in scraped:
            src_url = item.get("url", "")
            if src_url and not any(s["url"] == src_url for s in sources):
                sources.append({"url": src_url, "title": item.get("title", "")})

        await _emit(
            user_id, task_id, "complete",
            f"Done — {len(ranked[:15])} entities ready",
            count=len(ranked[:15]),
        )

        actions: List[Dict[str, Any]] = _build_actions(entity_schema)

        return ToolOutput(
            success=True,
            data=_build_response(
                intent_key, "entities",
                entities=ranked[:15],
                sources=sources,
                actions=actions,
            ),
        )

    # ── Route: research (raw scraped pages, no summarization) ────────────────

    async def _handle_research(
        self,
        query: str,
        search_queries: List[str],
        max_results: int,
        max_chars: int,
        user_id: str,
        task_id: str,
    ) -> ToolOutput:
        # 1. Search
        await _emit(user_id, task_id, "searching", f"Searching {len(search_queries)} queries")
        all_results, sources = await self._multi_search(
            search_queries, max_results, user_id, task_id,
        )
        await _emit(user_id, task_id, "search_complete", f"Found {len(all_results)} results", count=len(all_results))

        if not all_results:
            return ToolOutput(
                success=True,
                data=_build_response("research", "scraped_content", scraped_content=[], text="", sources=[]),
            )

        # 2. Scrape
        urls = [r["url"] for r in all_results]
        await _emit(user_id, task_id, "scraping", f"Scraping {min(len(urls), max_results)} pages", url_count=min(len(urls), max_results))
        scraped = await self._scrape_urls(urls, max_results, max_chars)

        # Trim and shape per page
        pages = [
            {
                "url": item.get("url", ""),
                "title": item.get("title", ""),
                "text": (item.get("text") or "")[:max_chars],
            }
            for item in scraped
            if item.get("text")
        ]
        # Pre-built concatenated context, ready to be passed straight into
        # ai_summarize via $.<step>.data.text — saves the chained tool from
        # having to reconstruct it.
        text_context = "\n\n---\n\n".join(
            f"Source: {p['url']}\nTitle: {p['title']}\nContent:\n{p['text']}"
            for p in pages
        )

        await _emit(user_id, task_id, "complete", f"Scraped {len(pages)} pages", count=len(pages))

        return ToolOutput(
            success=True,
            data=_build_response(
                "research", "scraped_content",
                scraped_content=pages,
                text=text_context,
                sources=sources,
            ),
        )

    # ── Shared helpers ───────────────────────────────────────────────────────

    async def _multi_search(
        self,
        search_queries: List[str],
        max_results: int,
        user_id: str = "",
        task_id: str = "",
    ) -> Tuple[List[Dict], List[Dict]]:
        """Run all queries in PARALLEL, deduplicate by URL, return (results, sources).

        Concurrency is bounded by ``_MAX_PARALLEL_SEARCHES`` and each query
        has its own ``asyncio.wait_for`` timeout (``_PER_QUERY_TIMEOUT_S``)
        so a single hung upstream search engine cannot stall the whole tool.
        Total query count is capped at ``_MAX_QUERIES`` to prevent SQH or
        fallback templates from over-loading the executor.
        """
        # Cap the query list defensively. Five parallel queries already gives
        # plenty of result diversity; more just slows the tool down.
        queries = list(dict.fromkeys(q.strip() for q in search_queries if q and q.strip()))
        if len(queries) > _MAX_QUERIES:
            _log.info(
                "web_research: capping %d queries to %d", len(queries), _MAX_QUERIES,
            )
            queries = queries[:_MAX_QUERIES]

        search_tool = WebSearchTool()
        sem = asyncio.Semaphore(_MAX_PARALLEL_SEARCHES)

        async def _run_one(q: str) -> Tuple[str, List[Dict]]:
            await _emit(user_id, task_id, "search_query", f"→ {q[:80]}", query=q)
            async with sem:
                try:
                    result = await asyncio.wait_for(
                        search_tool.execute({"query": q, "max_results": max_results}),
                        timeout=_PER_QUERY_TIMEOUT_S,
                    )
                    items = result.data.get("results", []) if result.success else []
                except asyncio.TimeoutError:
                    _log.warning("search query timed out (>%.1fs): %r", _PER_QUERY_TIMEOUT_S, q)
                    await _emit(
                        user_id, task_id, "search_query_timeout",
                        f"  ⏱  Timed out: {q[:60]}", query=q,
                    )
                    return q, []
                except Exception as exc:
                    _log.warning("search query %r failed: %s", q, exc)
                    return q, []
            await _emit(
                user_id, task_id, "search_query_done",
                f"  ← {len(items)} from: {q[:60]}",
                query=q, count=len(items),
            )
            return q, items

        results_per_query = await asyncio.gather(*(_run_one(q) for q in queries))

        seen_urls: set = set()
        all_results: List[Dict] = []
        sources: List[Dict] = []
        for _q, items in results_per_query:
            for item in items:
                url = item.get("url", "")
                if not url or url in seen_urls or _is_ad_redirect(url):
                    continue
                seen_urls.add(url)
                all_results.append(item)
                sources.append({
                    "url": url,
                    "title": item.get("title", ""),
                    "snippet": item.get("snippet", ""),
                })
        return all_results, sources

    async def _scrape_urls(
        self,
        urls: List[str],
        max_results: int,
        max_chars: int,
        use_nodriver: bool = False,
    ) -> List[Dict]:
        """Scrape via WebScrapeTool. Pass use_nodriver=True for entity pages to get
        rendered images from real Chrome instead of Playwright's image-blocked path.

        Wrapped in asyncio.wait_for so a hung Chrome/Playwright launch cannot
        stall the whole tool.
        """
        scrape_tool = WebScrapeTool(max_chars=max_chars)
        try:
            scrape_result = await asyncio.wait_for(
                scrape_tool._execute(
                    {
                        "base_links": urls[:max_results],
                        "max_results": max_results,
                        "use_nodriver": use_nodriver,
                    }
                ),
                timeout=_SCRAPE_TIMEOUT_S,
            )
            return scrape_result.data.get("results", [])
        except asyncio.TimeoutError:
            _log.warning(
                "scrape phase timed out (>%.0fs) for %d urls",
                _SCRAPE_TIMEOUT_S, len(urls),
            )
            return []


# ── Image enrichment ────────────────────────────────────────────────────────

def _enrich_images_from_scraped(
    entities: List[Dict],
    scraped: List[Dict],
) -> None:
    page_images: Dict[str, List[str]] = {}
    all_images: List[str] = []
    for item in scraped:
        imgs = item.get("images") or []
        url = item.get("url", "")
        if imgs:
            page_images[url] = imgs
            all_images.extend(imgs)

    used: set = set()
    for entity in entities:
        if entity.get("images"):
            continue
        src = entity.get("source_url", "")
        if src and src in page_images:
            picks = [u for u in page_images[src] if u not in used][:2]
            if picks:
                entity["images"] = picks
                used.update(picks)
                continue
        picks = [u for u in all_images if u not in used][:1]
        if picks:
            entity["images"] = picks
            used.update(picks)


# ── nodriver post-extraction image enrichment ───────────────────────────────

async def _enrich_images_nodriver(
    entities: List[Dict],
    top_n: int = 5,
    user_id: str = "",
    task_id: str = "",
) -> None:
    """Visit source_url of top entities that still lack images via nodriver.

    Gated: only runs if the average images-per-entity across the list is < 2,
    meaning we actually need more images. Only enriches the top `top_n` ranked
    entities. Total budget is _IMAGE_ENRICH_TIMEOUT_S (shared across all fetches).
    """
    if not entities:
        return
    avg_images = sum(len(e.get("images") or []) for e in entities) / len(entities)
    if avg_images >= 2:
        return

    targets = [
        e for e in entities[:top_n]
        if e.get("source_url") and not e.get("images")
    ]
    if not targets:
        return

    await _emit(user_id, task_id, "image_enrichment",
                f"Fetching images for {len(targets)} entities…",
                count=len(targets))

    from .scrape import WebScrapeTool
    scrape_tool = WebScrapeTool()

    async def _fetch_one(entity: Dict) -> None:
        url = entity.get("source_url", "")
        if not url:
            return
        try:
            result = await asyncio.wait_for(
                scrape_tool._scrape_nodriver(url),
                timeout=15.0,
            )
            imgs = result.get("images", [])
            if imgs:
                entity["images"] = imgs[:3]
        except Exception as exc:
            _log.debug("image enrichment failed for %s: %s", url, exc)

    try:
        await asyncio.wait_for(
            asyncio.gather(*[_fetch_one(e) for e in targets]),
            timeout=_IMAGE_ENRICH_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        _log.warning("image enrichment timed out (>%.0fs)", _IMAGE_ENRICH_TIMEOUT_S)


# ── Maps URL enrichment ─────────────────────────────────────────────────────

def _build_maps_url(name: str, location_hint: str = "") -> str:
    """Build a Google Maps search URL from entity name + location. Pure string op.

    Examples:
        ("Hotel Thousand", "Kathmandu, Bagmati") -> https://www.google.com/maps/search/?api=1&query=Hotel+Thousand%2C+Kathmandu%2C+Bagmati
        ("OYO 123", "")                          -> https://www.google.com/maps/search/?api=1&query=OYO+123
    """
    parts = [p for p in (name, location_hint) if p]
    q = ", ".join(parts).strip()
    if not q:
        return ""
    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(q)}"


def _enrich_maps_urls(entities: List[Dict], location: str = "") -> None:
    """Populate entity.maps_url from entity name + best-available location string."""
    for e in entities:
        if e.get("maps_url"):
            continue
        loc_hint = (
            e.get("address")
            or e.get("location")
            or location
            or ""
        )
        url = _build_maps_url(str(e.get("name", "")), str(loc_hint))
        if url:
            e["maps_url"] = url


# ── URL helpers ─────────────────────────────────────────────────────────────

_AD_REDIRECT_PATTERNS = ("bing.com/aclick", "google.com/aclk", "googleadservices.com")

def _is_ad_redirect(url: str) -> bool:
    return any(p in url for p in _AD_REDIRECT_PATTERNS)


# ── Location resolver ───────────────────────────────────────────────────────

_NEAR_ME_RE = re.compile(
    r"\bnear\s+(?:me|my\s+location|my\s+area)\b|\bnearby\b",
    flags=re.IGNORECASE,
)


def _inject_location(text: str, location: str) -> str:
    """Replace 'near me' / 'nearby' patterns and qualify city-only mentions with country.

    Two passes:
    1. Substitute 'near me' / 'nearby' / 'near my location' with 'City, Country'
       so DDGS gets an unambiguous place name (not just a bare city that could
       match a similarly-named place in another country — e.g. Janakpur → Jaipur).
    2. If the query already names the city but omits the country, append the
       country so search engines don't autocorrect to a more-popular homonym.
    """
    parts = [p.strip() for p in location.split(",") if p.strip()]
    city_part    = parts[0] if parts else location
    country_part = parts[-1] if len(parts) >= 2 else ""

    # Use "City, Country" as the substitution target so the search is unambiguous
    qualified = f"{city_part}, {country_part}" if country_part else city_part

    # Pass 1 — replace "near me" / "nearby" patterns
    result = text
    if _NEAR_ME_RE.search(text):
        result = _NEAR_ME_RE.sub(qualified, text)

    # Pass 2 — city is mentioned but country is not → append country
    if (city_part.lower() in result.lower()
            and country_part
            and country_part.lower() not in result.lower()):
        result = f"{result} {country_part}"

    return result


# ── Type label enrichment ───────────────────────────────────────────────────

def _enrich_type_labels(entities: List[Dict], entity_schema: str) -> None:
    label = _TYPE_LABELS.get(entity_schema, entity_schema.replace("_", " ").title())
    for e in entities:
        if not e.get("type_label"):
            e["type_label"] = label


# ── Actions builder ─────────────────────────────────────────────────────────

def _build_actions(entity_schema: str) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []
    if entity_schema in ("hotel", "restaurant", "event", "flight"):
        actions.append({"type": "book", "available": True})
    elif entity_schema == "product":
        actions.append({"type": "buy", "available": True})
    return actions


# ── Response builder ────────────────────────────────────────────────────────

def _build_response(
    intent: str,
    result_type: str,
    *,
    snippets: Optional[List[Dict]] = None,
    scraped_content: Optional[List[Dict]] = None,
    text: Optional[str] = None,
    entities: Optional[List[Dict]] = None,
    sources: Optional[List[Dict]] = None,
    actions: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    """Build the tool response. Only includes fields relevant to the intent.

    Variant fields are optional in OUTPUT_SCHEMA (see WebResearchTool) so the
    BaseTool validator does not warn when they're not included for a given
    intent. The validator must honor ``optional: true`` on schema fields.
    """
    resp: Dict[str, Any] = {
        "intent": intent,
        "result_type": result_type,
        "sources": sources or [],
    }
    if snippets is not None:
        resp["snippets"] = snippets
    if scraped_content is not None:
        resp["scraped_content"] = scraped_content
    if text is not None:
        resp["text"] = text
    if entities is not None:
        resp["entities"] = entities
    if actions is not None:
        resp["actions"] = actions
    return resp
