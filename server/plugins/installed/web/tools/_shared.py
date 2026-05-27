"""
Shared free functions for the web/tools package.

The web plugin houses two BaseTools that overlap on infrastructure but
diverge on intent:
  • web_research  — pure knowledge retrieval (factual_lookup / research).
  • entity_search — geo-aware entity discovery (hotels, restaurants, …).

This module owns the bits both tools need: tool_progress emission,
URL hygiene, "near me" location injection, the parallel-search runner,
the scrape wrapper, and the response envelope builders. Keeping them
here is the cleanest way to avoid one tool importing the other.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

from .scrape import WebScrapeTool
from .search import WebSearchTool

_log = logging.getLogger(__name__)


# ── Bounds shared by both pipelines ──────────────────────────────────────────
# Per-query / parallel / total caps. Tuned for an interactive assistant: any
# single upstream hang must not block the rest of the tool.
PER_QUERY_TIMEOUT_S = 12.0
MAX_PARALLEL_SEARCHES = 2
MAX_QUERIES = 3
SCRAPE_TIMEOUT_S = 35.0


# ── Live-progress emitter ────────────────────────────────────────────────────

async def emit_progress(
    tool_name: str,
    user_id: str,
    task_id: str,
    stage: str,
    message: str,
    **extra: Any,
) -> None:
    """Emit a ``tool_progress`` event for the calling tool. Best-effort.

    Both web_research and entity_search emit the same event shape; only
    ``tool_name`` differs.
    """
    if not user_id:
        return
    try:
        from app.socket.log_stream import emit_spark_log
        await emit_spark_log(
            user_id,
            "tool_progress",
            task_id=task_id,
            tool_name=tool_name,
            payload={"stage": stage, "message": message, **extra},
        )
    except Exception:  # pragma: no cover — never let UI emission break the tool
        pass


def make_emitter(tool_name: str) -> Callable[..., Awaitable[None]]:
    """Curry ``emit_progress`` with the tool name so callers can pass it
    around as a small ``emit`` callable."""
    async def _emit(user_id: str, task_id: str, stage: str, message: str, **extra: Any) -> None:
        await emit_progress(tool_name, user_id, task_id, stage, message, **extra)
    return _emit


# ── URL hygiene ──────────────────────────────────────────────────────────────

_AD_REDIRECT_PATTERNS = ("bing.com/aclick", "google.com/aclk", "googleadservices.com")


def is_ad_redirect(url: str) -> bool:
    """True for Bing/Google ad-redirect URLs that point through tracker
    domains. Skipping these saves a doomed scrape and avoids feeding the
    ranker tracker-domain noise."""
    return any(p in url for p in _AD_REDIRECT_PATTERNS)


# ── "Near me" / location resolver ────────────────────────────────────────────

_NEAR_ME_RE = re.compile(
    r"\bnear\s+(?:me|my\s+location|my\s+area)\b|\bnearby\b",
    flags=re.IGNORECASE,
)


def inject_location(text: str, location: str) -> str:
    """Replace 'near me' / 'nearby' patterns and qualify city-only mentions
    with country.

    Two passes:
      1. Substitute 'near me' / 'nearby' / 'near my location' with
         'City, Country' so the search engine gets an unambiguous place
         name (not just a bare city that could match a similarly-named
         place in another country — e.g. Janakpur → Jaipur).
      2. If the query already names the city but omits the country,
         append the country so search engines don't autocorrect to a
         more-popular homonym.
    """
    parts = [p.strip() for p in location.split(",") if p.strip()]
    city_part    = parts[0] if parts else location
    country_part = parts[-1] if len(parts) >= 2 else ""

    qualified = f"{city_part}, {country_part}" if country_part else city_part

    result = text
    if _NEAR_ME_RE.search(text):
        result = _NEAR_ME_RE.sub(qualified, text)

    if (
        city_part
        and country_part
        and city_part.lower() in result.lower()
        and country_part.lower() not in result.lower()
    ):
        result = f"{result} {country_part}"

    return result


# ── Parallel search runner ───────────────────────────────────────────────────

async def multi_search(
    search_queries: List[str],
    max_results: int,
    *,
    tool_name: str,
    user_id: str = "",
    task_id: str = "",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Run search queries in parallel, dedupe by URL, return ``(results, sources)``.

    Bounded by ``MAX_PARALLEL_SEARCHES`` and ``MAX_QUERIES``. Each query
    has its own ``asyncio.wait_for`` timeout so a single hung engine
    cannot stall the tool.
    """
    queries = list(dict.fromkeys(q.strip() for q in search_queries if q and q.strip()))
    if len(queries) > MAX_QUERIES:
        _log.info("%s: capping %d queries to %d", tool_name, len(queries), MAX_QUERIES)
        queries = queries[:MAX_QUERIES]

    search_tool = WebSearchTool()
    sem = asyncio.Semaphore(MAX_PARALLEL_SEARCHES)
    emit = make_emitter(tool_name)

    async def _run_one(q: str) -> Tuple[str, List[Dict[str, Any]]]:
        await emit(user_id, task_id, "search_query", f"→ {q[:80]}", query=q)
        async with sem:
            try:
                result = await asyncio.wait_for(
                    search_tool.execute({"query": q, "max_results": max_results}),
                    timeout=PER_QUERY_TIMEOUT_S,
                )
                items = result.data.get("results", []) if result.success else []
            except asyncio.TimeoutError:
                _log.warning("%s: search query timed out (>%.1fs): %r",
                             tool_name, PER_QUERY_TIMEOUT_S, q)
                await emit(user_id, task_id, "search_query_timeout",
                           f"  ⏱  Timed out: {q[:60]}", query=q)
                return q, []
            except Exception as exc:
                _log.warning("%s: search query %r failed: %s", tool_name, q, exc)
                return q, []
        await emit(user_id, task_id, "search_query_done",
                   f"  ← {len(items)} from: {q[:60]}", query=q, count=len(items))
        return q, items

    results_per_query = await asyncio.gather(*(_run_one(q) for q in queries))

    seen_urls: set = set()
    all_results: List[Dict[str, Any]] = []
    sources: List[Dict[str, Any]] = []
    for _q, items in results_per_query:
        for item in items:
            url = item.get("url", "")
            if not url or url in seen_urls or is_ad_redirect(url):
                continue
            seen_urls.add(url)
            all_results.append(item)
            sources.append({
                "url": url,
                "title": item.get("title", ""),
                "snippet": item.get("snippet", ""),
            })
    return all_results, sources


# ── Scrape wrapper ───────────────────────────────────────────────────────────

async def scrape_urls(
    urls: List[str],
    max_results: int,
    max_chars: int,
    *,
    use_nodriver: bool = False,
) -> List[Dict[str, Any]]:
    """Scrape via WebScrapeTool. ``use_nodriver=True`` for entity pages so we
    capture real images from rendered Chrome instead of Playwright's
    image-blocked path. Wrapped in ``asyncio.wait_for`` so a hung
    Chrome/Playwright launch cannot stall the caller."""
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
            timeout=SCRAPE_TIMEOUT_S,
        )
        return scrape_result.data.get("results", [])
    except asyncio.TimeoutError:
        _log.warning("scrape phase timed out (>%.0fs) for %d urls",
                     SCRAPE_TIMEOUT_S, len(urls))
        return []


# ── Numeric coercion (rejects NaN/inf) ───────────────────────────────────────

def safe_float(value: Any) -> Optional[float]:
    """Coerce to float, rejecting None / empty / NaN / ±inf.

    Rejecting NaN is critical so a malformed numeric input doesn't silently
    bypass downstream comparisons (NaN > x == False under IEEE 754).
    """
    import math
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


# ── Google Maps URL builder (used by entity_search image/maps enrichment) ────

def build_maps_url(name: str, location_hint: str = "") -> str:
    """Build a Google Maps search URL from name + location. Pure string op."""
    parts = [p for p in (name, location_hint) if p]
    q = ", ".join(parts).strip()
    if not q:
        return ""
    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(q)}"
