"""
entity_search — geo-aware entity discovery.

Responsibility
──────────────
Find *things* a user can act on — hotels, restaurants, hospitals,
attractions, products, movies, events, colleges, flights — and return
them as structured, ranked entities. The contract is:

  input:  query + intent + (optional) user coords / location
  output: {result_type: "entities", entities: […], sources: […], actions: […]}

How this differs from web_research
──────────────────────────────────
``web_research`` is *knowledge retrieval*: it produces snippets or
scraped prose for a downstream summarizer. Entity search is *entity
retrieval*: it produces structured, geo-validated objects ready for the
UI and for ``browser_action`` to act on.

Pipeline (per intent)
─────────────────────
  1. Resolve geography:
     • SQH-bound user_lat/user_lon if present, else
     • Query Geo Resolver — extracts place mention from query and forward-
       geocodes via Nominatim.
  2. Structured providers (multi_provider chain):
       google_places → foursquare → osm
     First non-empty wins. Cached. No scraping.
  3. If providers yield nothing, fall back to DDGS + scrape + LLM-extract
     (the legacy path, kept for non-OSM intents like flight/college/movie).
  4. Geo hard-discard + semantic rerank + city soft-filter via ``ranker``.
  5. Maps/type/image enrichment.

Architectural promise
─────────────────────
entity_search NEVER does knowledge summarization. It NEVER opens a
browser. Pure retrieval. See ``browser_action`` for transactional flows.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from app.plugins.tools.tool_base import BaseTool, ToolOutput

from . import _shared

_log = logging.getLogger(__name__)
_emit = _shared.make_emitter("entity_search")


# ── Intents owned by this tool ───────────────────────────────────────────────

_VALID_INTENTS = {
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
    "hotel_search":      "hotel",
    "product_search":    "product",
    "restaurant_search": "restaurant",
    "local_service":     "local_business",
    "person_search":     "person",
    "movie_search":      "movie",
    "event_search":      "event",
    "college_search":    "college",
    "place_search":      "place",
    "flight_search":     "flight",
}

_TYPE_LABELS = {
    "hotel":          "Hotel",
    "product":        "Product",
    "restaurant":     "Restaurant",
    "local_business": "Local Business",
    "person":         "Person",
    "movie":          "Movie / Show",
    "event":          "Event",
    "college":        "College",
    "place":          "Place",
    "flight":         "Flight",
}

# Intent-aware default geo hard-discard radii (km).
_DEFAULT_RADIUS_KM: Dict[str, float] = {
    "hotel_search":      30.0,
    "restaurant_search": 15.0,
    "local_service":     25.0,
    "place_search":      40.0,
    "event_search":      50.0,
}

# Site-scoped fallback queries for the DDGS path. Only intents OSM
# doesn't cover need rich fallbacks — for OSM-supported intents these
# rarely run, so keep them lean.
_SCRAPEABLE_SITE_QUERIES: Dict[str, List[str]] = {
    "hotel_search": [
        "site:budgetyourtrip.com cheap hotels {location}",
        "site:hostelworld.com {location} budget hostel hotel",
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
    "product_search": [
        "{query} price specifications",
        "{query} amazon OR flipkart OR ebay",
    ],
}

# Wall-clock caps. Mirrors the previous web_research budget so behaviour
# under load is unchanged.
_EXTRACT_TIMEOUT_S = 20.0
_IMAGE_ENRICH_TIMEOUT_S = 25.0
_TOTAL_TIMEOUT_S = 75.0


# ══════════════════════════════════════════════════════════════════════════════
# Tool
# ══════════════════════════════════════════════════════════════════════════════

class EntitySearchTool(BaseTool):
    """Geo-aware entity discovery.

    Inputs (set by SQH):
      query              (string, required)
      intent             (string, required)   — one of _VALID_INTENTS
      entity_schema      (string, optional)   — auto-derived from intent
      formatted_queries  (array, optional)    — for fallback DDGS path
      location           (string, optional)   — city/region or 'City, Country'
      latitude           (number, optional)   — user lat (from current_location)
      longitude          (number, optional)   — user lon
      max_radius_km      (number, optional)   — geo hard-discard radius
      max_results        (integer, optional)
      max_chars          (integer, optional)

    Output:
      {intent, result_type:"entities", entities:[…], sources:[…], actions:[…]}
    """

    TOOL_DESCRIPTION = (
        "Find structured entities the user can act on: hotels, restaurants, "
        "hospitals/clinics/gyms (local services), places to visit, events, "
        "movies/shows, colleges, flights, products, people. Returns ranked "
        "entities with coords, ratings, and booking URLs — never prose. "
        "Use this for any 'find me X' / 'X near me' / 'X in <city>' query. "
        "For factual knowledge or summaries, use web_research instead."
    )
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA: Dict[str, Any] = {
        "query": {"type": "string", "required": True},
        "intent": {
            "type": "string",
            "required": True,
            "enum": list(_VALID_INTENTS),
            "description": (
                "hotel_search | restaurant_search | local_service | place_search | "
                "event_search | person_search | movie_search | college_search | "
                "flight_search | product_search"
            ),
        },
        "entity_schema": {
            "type": "string",
            "required": False,
            "enum": [
                "hotel", "product", "restaurant", "local_business",
                "person", "movie", "event", "college", "place", "flight",
            ],
            "description": "Auto-derived from intent when omitted.",
        },
        "formatted_queries": {
            "type": "array",
            "required": False,
            "description": "Search strings for the DDGS fallback path.",
        },
        "location": {
            "type": "string",
            "required": False,
            "description": "City/region from current_location. Used for 'near me' substitution.",
        },
        "latitude": {
            "type": "number",
            "required": False,
            "description": "User latitude. Enables structured-provider retrieval and geo hard-filtering.",
        },
        "longitude": {
            "type": "number",
            "required": False,
            "description": "User longitude. Required alongside latitude.",
        },
        "max_radius_km": {
            "type": "number",
            "required": False,
            "description": "Geo hard-discard radius. Intent-aware defaults (hotel=30, restaurant=15, …).",
        },
        "max_results": {"type": "integer", "required": False, "default": 5},
        "max_chars": {"type": "integer", "required": False, "default": 5000},
    }
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {
            "intent":      {"type": "string"},
            "result_type": {"type": "string", "description": "entities"},
            "entities":    {"type": "array"},
            "sources":     {"type": "array"},
            "actions":     {"type": "array", "optional": True},
        },
        "error": {"type": "string"},
    }
    EXAMPLES = [
        {"user_utterance": "hotels in Mumbai"},
        {"user_utterance": "best restaurants near me"},
        {"user_utterance": "hospitals nearby"},
        {"user_utterance": "things to do in Tokyo"},
    ]
    SEMANTIC_TAGS = ["entity", "hotel", "restaurant", "place", "nearby", "search"]
    TOOL_CATEGORY = "entity_search"
    METADATA: Dict[str, Any] = {"summary_tts": "intent_search"}

    def get_tool_name(self) -> str:
        return "entity_search"

    # ── Entry point ──────────────────────────────────────────────────────────

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Wrap the real work in a wall-clock timeout — this tool must
        never hang the event loop."""
        try:
            return await asyncio.wait_for(self._execute_inner(inputs), timeout=_TOTAL_TIMEOUT_S)
        except asyncio.TimeoutError:
            user_id = str(inputs.get("_user_id") or inputs.get("user_id") or "")
            task_id = str(inputs.get("_task_id") or "")
            await _emit(user_id, task_id, "timeout",
                        f"entity_search timed out after {_TOTAL_TIMEOUT_S:.0f}s")
            _log.warning("entity_search total timeout (%.0fs) hit for query=%r",
                         _TOTAL_TIMEOUT_S, inputs.get("query"))
            return ToolOutput(
                success=False, data={},
                error=f"entity_search exceeded {_TOTAL_TIMEOUT_S:.0f}s wall-clock budget",
            )

    async def _execute_inner(self, inputs: Dict[str, Any]) -> ToolOutput:
        query = self.get_input(inputs, "query", "").strip()
        if not query:
            return ToolOutput(success=False, data={}, error="Query is required")

        intent = str(self.get_input(inputs, "intent", "") or "").lower()
        if intent not in _VALID_INTENTS:
            return ToolOutput(
                success=False, data={},
                error=f"intent {intent!r} is not an entity intent. Valid: {sorted(_VALID_INTENTS)}",
            )

        formatted_queries: List[str] = self.get_input(inputs, "formatted_queries", []) or []
        entity_schema: str = self.get_input(inputs, "entity_schema", "") or _ENTITY_INTENT_MAP[intent]
        location: str = str(self.get_input(inputs, "location", "") or "").strip()
        user_lat = _shared.safe_float(self.get_input(inputs, "latitude", None))
        user_lon = _shared.safe_float(self.get_input(inputs, "longitude", None))
        max_radius_km = _shared.safe_float(self.get_input(inputs, "max_radius_km", None))
        max_results = int(self.get_input(inputs, "max_results", 5) or 5)
        max_chars = int(self.get_input(inputs, "max_chars", 5000) or 5000)

        if not location and user_lat is not None and user_lon is not None:
            from ..providers import geo_resolver
            resolved_loc = await geo_resolver.reverse_geocode(user_lat, user_lon)
            if resolved_loc:
                location = ", ".join(p for p in [resolved_loc.city, resolved_loc.country] if p) or resolved_loc.display_name

        if location:
            query = _shared.inject_location(query, location)
            formatted_queries = [_shared.inject_location(q, location) for q in formatted_queries]

        search_queries = formatted_queries if formatted_queries else [query]

        user_id: str = str(inputs.get("_user_id") or inputs.get("user_id") or "")
        task_id: str = str(inputs.get("_task_id") or "")

        await _emit(
            user_id, task_id, "start",
            f"Searching {intent.replace('_', ' ')}: {query[:80]}",
            intent=intent,
        )

        return await self._handle(
            intent, query, search_queries, entity_schema,
            max_results, max_chars, location,
            user_lat, user_lon, max_radius_km,
            user_id, task_id,
        )

    # ── Core handler (replaces the old _handle_entity) ───────────────────────

    async def _handle(
        self,
        intent_key: str,
        query: str,
        search_queries: List[str],
        entity_schema: str,
        max_results: int,
        max_chars: int,
        location: str,
        user_lat: Optional[float],
        user_lon: Optional[float],
        max_radius_km: Optional[float],
        user_id: str,
        task_id: str,
    ) -> ToolOutput:
        radius_km = max_radius_km if max_radius_km else _DEFAULT_RADIUS_KM.get(intent_key)

        # ── Resolve coords from the query if SQH didn't bind them ────────────
        user_city: str = ""
        if user_lat is None or user_lon is None:
            from ..providers import geo_resolver
            resolved = await geo_resolver.resolve_query_geo(query)
            if resolved is not None:
                user_lat = resolved.lat
                user_lon = resolved.lon
                user_city = resolved.city or ""
                if not location and resolved.display_name:
                    location = ", ".join(
                        p for p in [resolved.city, resolved.country] if p
                    ) or resolved.display_name
                await _emit(
                    user_id, task_id, "geo_resolved",
                    f"Resolved query location → {location or resolved.display_name}",
                    lat=user_lat, lon=user_lon, city=user_city,
                )
        else:
            user_city = (location.split(",")[0].strip() if location else "")

        # ── Structured-provider primary path ─────────────────────────────────
        if user_lat is not None and user_lon is not None:
            from ..providers import multi_provider
            if multi_provider.supports(intent_key):
                await _emit(
                    user_id, task_id, "provider_search",
                    f"Querying structured providers for {intent_key.replace('_search', '')}…",
                    lat=user_lat, lon=user_lon, radius_km=radius_km,
                )
                try:
                    p_entities, p_sources = await multi_provider.search(
                        intent=intent_key,
                        query=query,
                        user_lat=user_lat,
                        user_lon=user_lon,
                        radius_km=radius_km or 25.0,
                        max_results=max(max_results * 3, 20),
                    )
                except Exception as exc:  # pragma: no cover — must never crash the tool
                    _log.warning("multi_provider failed: %s — falling back to web search", exc)
                    p_entities, p_sources = [], []

                if p_entities:
                    from .ranker import rank_entities
                    ranked = await rank_entities(
                        p_entities, entity_schema, query,
                        user_lat=user_lat, user_lon=user_lon,
                        max_radius_km=radius_km,
                        user_city=user_city or None,
                    )
                    _enrich_maps_urls(ranked, location)
                    _enrich_type_labels(ranked, entity_schema)
                    await _enrich_images_nodriver(ranked, top_n=5, user_id=user_id, task_id=task_id, user_city=user_city)
                    winning_source = ranked[0].get("source") if ranked else None
                    await _emit(
                        user_id, task_id, "complete",
                        f"Done — {len(ranked[:15])} results via {winning_source or 'providers'}",
                        count=len(ranked[:15]),
                        provider=winning_source,
                    )
                    return ToolOutput(
                        success=True,
                        data=_build_response(
                            intent_key,
                            entities=ranked[:15],
                            sources=p_sources,
                            actions=_build_actions(entity_schema),
                        ),
                    )
                await _emit(
                    user_id, task_id, "provider_fallback",
                    "Structured providers returned no results — falling back to web search",
                )

        # ── DDGS + LLM-extract fallback (for non-OSM intents or empty primaries) ─
        fallback_templates = _SCRAPEABLE_SITE_QUERIES.get(intent_key, [])
        loc = location or query
        fallback_queries = [t.format(location=loc, query=query) for t in fallback_templates]
        all_search_queries = list(dict.fromkeys(search_queries + fallback_queries))

        await _emit(
            user_id, task_id, "searching",
            f"Searching {len(all_search_queries)} queries in parallel",
            queries=all_search_queries[:6],
        )
        all_results, sources = await _shared.multi_search(
            all_search_queries, max_results,
            tool_name="entity_search", user_id=user_id, task_id=task_id,
        )
        await _emit(user_id, task_id, "search_complete",
                    f"Found {len(all_results)} unique results", count=len(all_results))

        if not all_results:
            return ToolOutput(
                success=True,
                data=_build_response(intent_key, entities=[], sources=[]),
            )

        urls = [r["url"] for r in all_results if not _shared.is_ad_redirect(r["url"])]
        if not urls:
            urls = [r["url"] for r in all_results]
        await _emit(user_id, task_id, "scraping",
                    f"Scraping {min(len(urls), max_results)} pages",
                    url_count=min(len(urls), max_results),
                    urls=[{"url": u, "domain": urlparse(u).netloc.replace("www.", "")}
                          for u in urls[:max_results]])
        scraped = await _shared.scrape_urls(
            urls, max_results, max_chars,
            use_nodriver=True,
            user_id=user_id, task_id=task_id, tool_name="entity_search",
        )
        scraped_with_text = [s for s in scraped if s.get("text")]
        await _emit(user_id, task_id, "scrape_complete",
                    f"Scraped {len(scraped_with_text)} pages",
                    count=len(scraped_with_text))

        if not scraped_with_text:
            scraped_with_text = [
                {"url": r.get("url", ""), "title": r.get("title", ""),
                 "text": f"{r.get('title', '')}. {r.get('snippet', '')}"}
                for r in all_results if r.get("snippet")
            ]

        await _emit(user_id, task_id, "extracting",
                    f"Extracting {entity_schema} entities")
        from .entity_extractor import extract_entities
        try:
            entities = await asyncio.wait_for(
                extract_entities(scraped_with_text, entity_schema, query, location),
                timeout=_EXTRACT_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            _log.warning("entity extraction timed out (>%.0fs) for %s",
                         _EXTRACT_TIMEOUT_S, entity_schema)
            await _emit(user_id, task_id, "extract_timeout",
                        f"⏱  Entity extraction timed out after {_EXTRACT_TIMEOUT_S:.0f}s")
            entities = []
        await _emit(user_id, task_id, "extract_complete",
                    f"Extracted {len(entities)} entities", count=len(entities))

        from .ranker import rank_entities
        ranked = await rank_entities(
            entities, entity_schema, query,
            user_lat=user_lat, user_lon=user_lon,
            max_radius_km=radius_km,
            user_city=user_city or None,
        )

        _enrich_images_from_scraped(ranked, scraped)
        await _enrich_images_nodriver(ranked, top_n=5, user_id=user_id, task_id=task_id, user_city=user_city)
        _enrich_maps_urls(ranked, location)
        _enrich_type_labels(ranked, entity_schema)

        for item in scraped:
            src_url = item.get("url", "")
            if src_url and not any(s["url"] == src_url for s in sources):
                sources.append({"url": src_url, "title": item.get("title", "")})

        await _emit(user_id, task_id, "complete",
                    f"Done — {len(ranked[:15])} entities ready",
                    count=len(ranked[:15]))

        return ToolOutput(
            success=True,
            data=_build_response(
                intent_key,
                entities=ranked[:15],
                sources=sources,
                actions=_build_actions(entity_schema),
            ),
        )


# ── Enrichers (entity-specific; do not belong in _shared) ────────────────────

def _enrich_images_from_scraped(entities: List[Dict], scraped: List[Dict]) -> None:
    page_images: Dict[str, List[str]] = {}
    all_images: List[str] = []
    for item in scraped:
        imgs = [u for u in (item.get("images") or []) if _shared.is_valid_image_url(u)]
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


async def _enrich_images_nodriver(
    entities: List[Dict],
    top_n: int = 5,
    user_id: str = "",
    task_id: str = "",
    user_city: str = "",
) -> None:
    """Multi-tiered image enrichment.

    Strategy per entity (stops at first success):
      1. Static httpx scrape of official website (fast, <1s)
      2. Image search via _shared.search_images — DDG with Bing fallback (~2s)
      3. Nodriver scrape of venue page found via web search (slow, 5-10s)

    Per-entity gating: any entity in the top_n whose existing ``images`` list
    has zero *valid* URLs is a target. We deliberately don't short-circuit on
    a global average — that used to leave half the list with empty thumbnails
    whenever providers returned a couple of placeholder images.
    """
    if not entities:
        return

    def _has_valid_image(e: Dict) -> bool:
        return any(_shared.is_valid_image_url(u) for u in (e.get("images") or []))

    targets = [e for e in entities[:top_n] if not _has_valid_image(e)]
    if not targets:
        return

    await _emit(user_id, task_id, "image_enrichment",
                f"Fetching images for {len(targets)} entities\u2026",
                count=len(targets))

    from .scrape import WebScrapeTool
    scrape_tool = WebScrapeTool()

    async def _fetch_one(entity: Dict) -> None:
        name = entity.get("name", "")

        # ── Tier 1: fast static scrape of official website ────────────
        website = entity.get("website") or ""
        if website:
            if not website.startswith("http"):
                website = "http://" + website
            # Skip sites that never return useful images via static fetch
            skip_static = ("facebook.com", "instagram.com", "twitter.com", "x.com")
            if not any(d in website for d in skip_static):
                try:
                    res = await asyncio.wait_for(
                        scrape_tool._scrape_httpx(website), timeout=5.0,
                    )
                    if res and res.get("images"):
                        filtered = [i for i in res["images"] if _shared.is_valid_image_url(i)]
                        if filtered:
                            entity["images"] = filtered[:3]
                            return
                except Exception:
                    pass  # fall through to next tier

        # ── Tier 2: multi-source image search (DDG → Bing fallback) ───
        if name:
            search_q = " ".join(p for p in (name, user_city) if p).strip()
            imgs = await _shared.search_images(search_q, limit=3)
            if imgs:
                entity["images"] = imgs[:3]
                return

        # ── Tier 3: nodriver scrape of official website or venue page ─
        scrape_url = website or ""
        if not scrape_url:
            # Try to discover a venue page via web search
            if name:
                try:
                    from .search import WebSearchTool
                    search_tool = WebSearchTool()
                    search_res = await search_tool._fetch_and_rank(
                        f"{name} {user_city}".strip(), limit=1,
                    )
                    if search_res:
                        scrape_url = search_res[0].get("url") or ""
                except Exception:
                    pass

        if scrape_url and "openstreetmap.org" not in scrape_url:
            try:
                res = await asyncio.wait_for(
                    scrape_tool._scrape_nodriver(scrape_url), timeout=12.0,
                )
                if res and res.get("images"):
                    filtered = [i for i in res["images"] if _shared.is_valid_image_url(i)]
                    if filtered:
                        entity["images"] = filtered[:3]
                        return
            except Exception:
                pass

    try:
        await asyncio.wait_for(
            asyncio.gather(*[_fetch_one(e) for e in targets]),
            timeout=_IMAGE_ENRICH_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        _log.warning("image enrichment timed out (>%.0fs)", _IMAGE_ENRICH_TIMEOUT_S)


def _enrich_maps_urls(entities: List[Dict], location: str = "") -> None:
    """Populate entity.maps_url from name + best-available location string."""
    for e in entities:
        if e.get("maps_url"):
            continue
        loc_hint = e.get("address") or e.get("location") or location or ""
        url = _shared.build_maps_url(str(e.get("name", "")), str(loc_hint))
        if url:
            e["maps_url"] = url


def _enrich_type_labels(entities: List[Dict], entity_schema: str) -> None:
    label = _TYPE_LABELS.get(entity_schema, entity_schema.replace("_", " ").title())
    for e in entities:
        if not e.get("type_label"):
            e["type_label"] = label


def _build_actions(entity_schema: str) -> List[Dict[str, Any]]:
    """Hint the UI about which transactional actions apply to this schema.
    The ``browser_action`` tool consumes these (or it's invoked directly)."""
    actions: List[Dict[str, Any]] = []
    if entity_schema in ("hotel", "restaurant", "event", "flight"):
        actions.append({"type": "book", "available": True})
    elif entity_schema == "product":
        actions.append({"type": "buy", "available": True})
    return actions


def _build_response(
    intent: str,
    *,
    entities: Optional[List[Dict]] = None,
    sources: Optional[List[Dict]] = None,
    actions: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    """Standard entity-search response envelope."""
    resp: Dict[str, Any] = {
        "intent":      intent,
        "result_type": "entities",
        "entities":    entities or [],
        "sources":     sources or [],
    }
    if actions is not None:
        resp["actions"] = actions
    return resp


__all__ = ["EntitySearchTool"]
