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
import json
import logging
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote_plus, urlparse

import httpx

from .scrape import WebScrapeTool
from .search import WebSearchTool

_log = logging.getLogger(__name__)


# ── Bounds shared by both pipelines ──────────────────────────────────────────
# Per-query / parallel / total caps. Tuned for an interactive assistant: any
# single upstream hang must not block the rest of the tool.
PER_QUERY_TIMEOUT_S = 12.0
MAX_PARALLEL_SEARCHES = 2
MAX_QUERIES = 3
SCRAPE_TIMEOUT_S = 25.0       # primary scrape budget (was 35s)
SCRAPE_RETRY_TIMEOUT_S = 15.0 # retry budget when 0 pages returned text


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
    user_id: str = "",
    task_id: str = "",
    tool_name: str = "",
) -> List[Dict[str, Any]]:
    """Scrape via WebScrapeTool with automatic retry.

    If the primary attempt yields 0 pages with text (all nodriver/playwright
    failed), automatically retries with plain httpx (use_nodriver=False) using
    a shorter budget. This covers the common Windows case where nodriver errors
    out immediately but static httpx can still read SSR pages.
    """
    scrape_tool = WebScrapeTool(max_chars=max_chars)

    async def _attempt(nd: bool, budget: float) -> List[Dict[str, Any]]:
        try:
            result = await asyncio.wait_for(
                scrape_tool._execute({
                    "base_links": urls[:max_results],
                    "max_results": max_results,
                    "use_nodriver": nd,
                }),
                timeout=budget,
            )
            return result.data.get("results", [])
        except asyncio.TimeoutError:
            _log.warning("scrape phase timed out (>%.0fs) for %d urls", budget, len(urls))
            return []

    scraped = await _attempt(use_nodriver, SCRAPE_TIMEOUT_S)

    # Auto-retry with plain httpx when every URL came back empty
    if use_nodriver and not any(s.get("text") for s in scraped):
        _log.info("scrape_urls: 0 pages with text — retrying without nodriver")
        if user_id:
            await emit_progress(
                tool_name or "scrape", user_id, task_id,
                "scrape_retry",
                "Scraped 0 pages — retrying with httpx…",
            )
        retry = await _attempt(False, SCRAPE_RETRY_TIMEOUT_S)
        if any(s.get("text") for s in retry):
            return retry

    return scraped


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


# ── Image URL filter + multi-source image search ────────────────────────────
#
# These live in _shared because both entity_search (venue photos) and
# web_research (person/topic images) need them.
#
# Lesson learned: the previous filter used substring matches like "theme" or
# "logo" which dropped legitimate CDN URLs that happened to carry those words
# in query params. The version below splits hosts from paths and checks both
# carefully — fewer false positives without losing the tracker/sprite drops.

_IMAGE_SKIP_HOSTS = (
    "matomo.openstreetmap.org",
    "google-analytics.com",
    "googletagmanager.com",
    "doubleclick.net",
    "facebook.com/tr",
    "gstatic.com",
    "maps.wikimedia.org",
)
_IMAGE_SKIP_PATH_FRAGMENTS = (
    "/favicon",
    "/sprite",
    "/spacer",
    "/pixel.",
    "/blank.",
    "/1x1.",
    "/tiny.",
    "/placeholder",
    "/icons/",
    "/wp-content/themes/",
    "/assets/banners/",
    "/banners/",
    "/matomo.php",
)
_IMAGE_BAD_EXT_RE = re.compile(r"\.(svg|ico)(\?|#|$)", re.IGNORECASE)


def is_valid_image_url(url: str) -> bool:
    """Path/host-aware filter for image URLs.

    Drops tracking pixels, favicons, sprites, theme/banner decoration and
    .svg/.ico/(non-photo) .gif — without nuking legit CDN URLs that carry
    'logo' or 'theme' inside opaque query strings.
    """
    if not url or not isinstance(url, str):
        return False
    if not url.startswith("http"):
        return False
    try:
        parsed = urlparse(url.lower())
    except Exception:
        return False
    host = parsed.netloc
    path = parsed.path

    if any(frag in host for frag in _IMAGE_SKIP_HOSTS):
        return False
    if any(frag in path for frag in _IMAGE_SKIP_PATH_FRAGMENTS):
        return False
    if _IMAGE_BAD_EXT_RE.search(path):
        return False
    # .gif allowed only when filename hints at a photo (rare but legit)
    if path.endswith(".gif") and not any(t in path for t in ("photo", "image")):
        return False
    return True


# Serialize DDG image calls — concurrent hits earn instant 403s.
_DDG_IMAGE_SEM: Optional[asyncio.Semaphore] = None


def _get_ddg_image_sem() -> asyncio.Semaphore:
    # Use a local var so the type checker can narrow `Optional[Semaphore]`
    # to `Semaphore` after the None-check; assigning back to the module
    # global directly would leave the return value typed as Optional.
    global _DDG_IMAGE_SEM
    sem = _DDG_IMAGE_SEM
    if sem is None:
        sem = asyncio.Semaphore(1)
        _DDG_IMAGE_SEM = sem
    return sem


async def _ddg_images(query: str, limit: int = 3) -> List[str]:
    """ddgs.images() — single attempt, serialized. Returns [] on any failure."""
    async with _get_ddg_image_sem():
        try:
            from ddgs import DDGS

            def _sync():
                with DDGS(timeout=8) as ddgs:
                    return list(ddgs.images(
                        query, max_results=limit * 2, safesearch="moderate",
                    ))

            loop = asyncio.get_running_loop()
            results = await loop.run_in_executor(None, _sync)
            out = [
                r["image"] for r in results
                if r.get("image") and is_valid_image_url(r["image"])
            ]
            return out[:limit]
        except Exception as exc:
            _log.debug("ddg images failed for %s: %s", query, exc)
            return []


_BING_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
# Bing embeds image metadata as JSON in m="..." attributes. The JSON itself
# always contains "murl" (media URL) — a much more reliable anchor than the
# surrounding class name, which Bing rotates. We accept any m="..." that
# parses to a dict carrying murl, dropping nav/ad noise via the JSON shape.
_BING_M_ATTR_RE = re.compile(r'm="(\{[^"]*murl[^"]*\})"', re.IGNORECASE)


async def _bing_images(query: str, limit: int = 3) -> List[str]:
    """Scrape Bing Images for direct image URLs.

    Uses the ``/images/async`` endpoint which returns a deterministic
    fragment of result anchors — far more reliable than the front-door
    HTML, which sometimes serves a stripped/interstitial page to
    server-side clients.
    """
    # Ask for a bigger pool than we need so the filter can drop garbage.
    fetch_count = max(limit * 4, 20)
    search_url = (
        "https://www.bing.com/images/async"
        f"?q={quote_plus(query)}&first=1&count={fetch_count}"
        "&relp=35&scenario=ImageBasicHover&safeSearch=Moderate"
    )
    headers = {**_BING_HEADERS, "X-Requested-With": "XMLHttpRequest"}
    try:
        async with httpx.AsyncClient(
            timeout=6.0, headers=headers, follow_redirects=True,
        ) as client:
            resp = await client.get(search_url)
            if resp.status_code != 200:
                return []
            html = resp.text
    except Exception as exc:
        _log.debug("bing images fetch failed for %s: %s", query, exc)
        return []

    images: List[str] = []
    for raw in _BING_M_ATTR_RE.findall(html):
        if len(images) >= limit:
            break
        try:
            meta = json.loads(raw.replace("&quot;", '"'))
        except Exception:
            continue
        if not isinstance(meta, dict):
            continue
        img_url = meta.get("murl") or meta.get("turl") or ""
        if img_url and is_valid_image_url(img_url) and img_url not in images:
            images.append(img_url)
    return images


# ── Yandex (best coverage for obscure venues — TripAdvisor/Booking photos) ──
#
# Yandex's HTML embeds image metadata as HTML-encoded JSON inside many
# attribute values. We don't try to parse the JSON — a targeted regex on
# the encoded `img_href` field is far more robust against Yandex's
# layout changes than walking the DOM.
_YANDEX_IMG_HREF_RE = re.compile(
    r'img_href&quot;:&quot;(https?://[^&]+)&quot;',
    re.IGNORECASE,
)


async def _yandex_images(query: str, limit: int = 3) -> List[str]:
    """Scrape Yandex Images. Yandex consistently has the best coverage for
    obscure venues (small cafés, regional hotels) — its image index pulls
    heavily from TripAdvisor, Booking, and other travel sites. The trade-off
    is occasional rate-limiting; we fail soft and let later tiers cover."""
    search_url = f"https://yandex.com/images/search?text={quote_plus(query)}"
    try:
        async with httpx.AsyncClient(
            timeout=6.0, headers=_BING_HEADERS, follow_redirects=True,
        ) as client:
            resp = await client.get(search_url)
            if resp.status_code != 200:
                return []
            html = resp.text
    except Exception as exc:
        _log.debug("yandex images fetch failed for %s: %s", query, exc)
        return []

    images: List[str] = []
    for img_url in _YANDEX_IMG_HREF_RE.findall(html):
        if len(images) >= limit:
            break
        if is_valid_image_url(img_url) and img_url not in images:
            images.append(img_url)
    return images


# ── Wikipedia (proper-noun fallback) ────────────────────────────────────────
#
# Wikipedia's MediaWiki API returns the lead image of pages matching a search
# in one round-trip. It's the most reliable source for famous people, places,
# landmarks, and well-known businesses — but it produces nothing for obscure
# entities, which is why it sits at the bottom of the chain.
_WIKIPEDIA_HEADERS = {
    # Wikipedia rejects generic UAs; a meaningful identifier is required.
    "User-Agent": "SparkAI-image-enrichment/1.0",
    "Accept": "application/json",
}


async def _wikipedia_images(query: str, limit: int = 3) -> List[str]:
    """Look up lead images of Wikipedia pages matching the query.

    One API call fetches the top search hits *and* their thumbnails — no
    second round-trip needed. ``pithumbsize`` controls thumbnail width.
    """
    api_url = (
        "https://en.wikipedia.org/w/api.php"
        "?action=query&format=json&prop=pageimages"
        f"&generator=search&gsrsearch={quote_plus(query)}"
        f"&gsrlimit={max(limit, 3)}&pithumbsize=600"
    )
    try:
        async with httpx.AsyncClient(
            timeout=6.0, headers=_WIKIPEDIA_HEADERS, follow_redirects=True,
        ) as client:
            resp = await client.get(api_url)
            if resp.status_code != 200:
                return []
            data = resp.json()
    except Exception as exc:
        _log.debug("wikipedia images fetch failed for %s: %s", query, exc)
        return []

    pages = (data.get("query") or {}).get("pages") or {}
    if not isinstance(pages, dict):
        return []

    # Sort by search rank so the best-matching article wins, not the one
    # with the highest pageid (which is essentially random).
    ranked = sorted(
        pages.values(),
        key=lambda p: p.get("index", 9999) if isinstance(p, dict) else 9999,
    )
    images: List[str] = []
    for page in ranked:
        if len(images) >= limit:
            break
        if not isinstance(page, dict):
            continue
        thumb = (page.get("thumbnail") or {}).get("source")
        if isinstance(thumb, str) and is_valid_image_url(thumb) and thumb not in images:
            images.append(thumb)
    return images


# ── Tiered orchestrator ──────────────────────────────────────────────────────

async def search_images(
    query: str,
    limit: int = 3,
) -> List[str]:
    """Multi-source image search with a tiered fallback chain.

    Order (each tier short-circuits the rest if it returns anything):
      1. DuckDuckGo (``ddgs.images()``) — fastest, often rate-limited.
      2. Yandex Images — best coverage for obscure venues / non-Western entities.
      3. Bing Images — always available, decent results for common queries.
      4. Wikipedia API — proper-noun last resort (people, landmarks).

    Yandex is preferred over Bing because Bing's image index is weak for
    Nepali/Indian/regional venues — Yandex pulls from TripAdvisor and
    Booking and returns photos of the actual place. Wikipedia stays last
    because it returns nothing for non-encyclopedic entities.

    Always returns a list (possibly empty). Never raises.
    """
    if not query:
        return []

    for fetcher in (_ddg_images, _yandex_images, _bing_images, _wikipedia_images):
        imgs = await fetcher(query, limit)
        if imgs:
            return imgs

    return []
