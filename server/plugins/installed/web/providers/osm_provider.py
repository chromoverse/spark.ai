"""
OpenStreetMap structured-retrieval provider.

Why OSM
───────
Free, open, no API key, globally consistent coords + tags. Outperforms
DDGS+SEO scraping for nearby-entity intents because every result has
ground-truth geography. This is the foundation that fixes
"Miami hotels appearing for a Kathmandu query".

Pipeline
────────
1. ``provider_registry.overpass_filters(intent, query)`` chooses the OSM
   tag filter (e.g. ``amenity=hospital``).
2. Single Overpass QL union query around (lat, lon) with radius.
3. Parse OSM elements → ``ProviderEntity`` → per-intent shape dict.
4. Return ``(entities, sources)`` ready to flow into the existing ranker.

Resilience
──────────
Overpass is community-run; expect intermittent 5xx and slow responses.
We hit a small list of public mirrors, bounded by ``_TOTAL_TIMEOUT_S``,
and quietly return empty on failure so the caller falls back to DDGS.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

import httpx

from .provider_models import ProviderEntity
from .provider_registry import overpass_filters, supported_intents

logger = logging.getLogger(__name__)

# ── Limits ───────────────────────────────────────────────────────────────────
_OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
]
_PER_ENDPOINT_TIMEOUT_S = 6.0
_TOTAL_TIMEOUT_S = 8.0
_HTTP_HEADERS = {
    "User-Agent": "SparkAI/1.0 (https://github.com/SiddTheCoder) web_research/osm_provider",
    "Accept": "application/json",
}

# ── Concurrency / circuit breaker / cache ───────────────────────────────────
# Overpass is community-run — without these guards a flaky mirror or a
# stampede of "near me" requests would recreate the DDGS hang problem.

# Cap concurrent Overpass calls across the whole server. Two parallel
# searches is plenty for an interactive desktop assistant and keeps us
# well under Overpass's per-IP rate limits.
_MAX_CONCURRENT = 2
_GLOBAL_SEMAPHORE = asyncio.Semaphore(_MAX_CONCURRENT)

# Circuit breaker: skip an endpoint for ``_BREAKER_COOLDOWN_S`` after
# ``_BREAKER_FAIL_THRESHOLD`` consecutive failures. Open circuits close
# automatically once cooldown elapses — single success resets the counter.
_BREAKER_FAIL_THRESHOLD = 3
_BREAKER_COOLDOWN_S = 60.0
_breaker_state: Dict[str, Dict[str, float]] = {
    url: {"fails": 0.0, "open_until": 0.0} for url in _OVERPASS_ENDPOINTS
}

# In-process TTL cache. Key rounds coords to ~1km grid and normalizes the
# query keywords so "best hotels near me" and "hotels near me" share a key.
# 10 min is short enough for opening_hours / venue churn but long enough
# to absorb retry stampedes.
_CACHE_TTL_S = 600.0
_CACHE_MAX_ENTRIES = 256
_cache: Dict[str, Tuple[float, List[Dict[str, Any]], List[Dict[str, Any]]]] = {}


def _now() -> float:
    return time.monotonic()


def _cache_key(intent: str, query: str, lat: float, lon: float, radius_km: float) -> str:
    # ~1km grid via 2 decimals. Query → sorted alpha tokens so phrasing
    # variants collapse to the same key.
    tokens = sorted(set(re.findall(r"[a-z0-9]+", query.lower())))
    payload = f"{intent}|{round(lat, 2)}|{round(lon, 2)}|{round(radius_km, 1)}|{','.join(tokens)}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> Optional[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]]:
    hit = _cache.get(key)
    if hit is None:
        return None
    ts, ents, srcs = hit
    if _now() - ts > _CACHE_TTL_S:
        _cache.pop(key, None)
        return None
    return ents, srcs


def _cache_put(
    key: str,
    entities: List[Dict[str, Any]],
    sources: List[Dict[str, Any]],
) -> None:
    if len(_cache) >= _CACHE_MAX_ENTRIES:
        # Evict oldest. Linear scan is fine for ~256 entries.
        oldest = min(_cache.items(), key=lambda kv: kv[1][0])[0]
        _cache.pop(oldest, None)
    _cache[key] = (_now(), entities, sources)


def _breaker_open(url: str) -> bool:
    state = _breaker_state.get(url)
    if state is None:
        return False
    return state["open_until"] > _now()


def _breaker_record_failure(url: str) -> None:
    state = _breaker_state.setdefault(url, {"fails": 0.0, "open_until": 0.0})
    state["fails"] += 1
    if state["fails"] >= _BREAKER_FAIL_THRESHOLD:
        state["open_until"] = _now() + _BREAKER_COOLDOWN_S
        logger.warning(
            "OSM circuit breaker OPEN for %s (fails=%d, cooldown=%.0fs)",
            url, int(state["fails"]), _BREAKER_COOLDOWN_S,
        )


def _breaker_record_success(url: str) -> None:
    state = _breaker_state.setdefault(url, {"fails": 0.0, "open_until": 0.0})
    state["fails"] = 0.0
    state["open_until"] = 0.0


# ══════════════════════════════════════════════════════════════════════════════
# Public interface
# ══════════════════════════════════════════════════════════════════════════════

def supports(intent: str) -> bool:
    """Whether OSM has a structured filter for this intent."""
    return intent in supported_intents()


async def search(
    intent: str,
    query: str,
    user_lat: float,
    user_lon: float,
    radius_km: float = 25.0,
    max_results: int = 25,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Run a nearby-entity search via Overpass.

    Returns ``(entities, sources)`` where ``entities`` is a list of dicts
    in the schema-shape the ranker/UI expects (matches EntitySchema fields)
    and ``sources`` is the standard ``[{url, title, snippet}]`` shape.

    Empty list on any failure — the caller is expected to fall back to
    its existing DDGS+scrape+LLM path.
    """
    filters = await overpass_filters(intent, query)
    if not filters:
        logger.debug("OSM: no filter mapping for intent=%s query=%r", intent, query)
        return [], []

    radius_m = int(max(500.0, min(radius_km * 1000.0, 50_000.0)))

    # Cache check — coord-rounded so neighbouring requests share results.
    ckey = _cache_key(intent, query, user_lat, user_lon, radius_km)
    cached = _cache_get(ckey)
    if cached is not None:
        ents, srcs = cached
        logger.info("OSM: cache hit (%d entities) for %s near (%.4f, %.4f)",
                    len(ents), intent, user_lat, user_lon)
        return ents[:max_results], srcs[:max_results]

    overpass_query = _build_overpass_query(filters, user_lat, user_lon, radius_m)

    # Global concurrency cap — protects Overpass mirrors AND our executor.
    async with _GLOBAL_SEMAPHORE:
        elements = await _execute_overpass(overpass_query)

    if not elements:
        # Negative-cache short TTL would be nice; for now skip to keep
        # behaviour obvious (no result → fall back to DDGS immediately).
        return [], []

    provider_entities = _parse_elements(elements, intent)
    # Cap before reshape so we don't hand 500 entities to downstream enrichment.
    provider_entities = provider_entities[:max_results]

    entities = [_to_schema_dict(p, intent) for p in provider_entities]
    sources = _build_sources(provider_entities)
    _cache_put(ckey, entities, sources)
    logger.info(
        "OSM: returned %d %s entities within %dm of (%.4f, %.4f)",
        len(entities), intent, radius_m, user_lat, user_lon,
    )
    return entities, sources


# ══════════════════════════════════════════════════════════════════════════════
# Overpass client
# ══════════════════════════════════════════════════════════════════════════════

def _build_overpass_query(
    filters: List[str],
    lat: float,
    lon: float,
    radius_m: int,
) -> str:
    """Assemble an Overpass QL union query bounded to the given radius."""
    body = "\n".join(f"  {f}(around:{radius_m},{lat},{lon});" for f in filters)
    return (
        f"[out:json][timeout:{int(_PER_ENDPOINT_TIMEOUT_S)}];\n"
        f"(\n{body}\n);\n"
        "out tags center 60;"
    )


async def _execute_overpass(query: str) -> List[Dict[str, Any]]:
    """Try each Overpass mirror in turn; return the first non-empty payload.

    Endpoints behind an open circuit breaker are skipped. A success closes
    the breaker; consecutive failures open it. Per-endpoint timeout is
    short and the whole call is bounded by ``_TOTAL_TIMEOUT_S``.
    """
    async def _one(client: httpx.AsyncClient, url: str) -> List[Dict[str, Any]]:
        try:
            resp = await client.post(
                url,
                data={"data": query},
                timeout=_PER_ENDPOINT_TIMEOUT_S,
            )
            if resp.status_code != 200:
                logger.debug("OSM: %s returned %d", url, resp.status_code)
                _breaker_record_failure(url)
                return []
            payload = resp.json()
            elements = payload.get("elements") or []
            _breaker_record_success(url)
            return elements
        except Exception as exc:
            logger.debug("OSM: %s failed: %s", url, exc)
            _breaker_record_failure(url)
            return []

    deadline = _now() + _TOTAL_TIMEOUT_S
    try:
        async with httpx.AsyncClient(headers=_HTTP_HEADERS) as client:
            for endpoint in _OVERPASS_ENDPOINTS:
                if _breaker_open(endpoint):
                    logger.debug("OSM: skipping %s (circuit open)", endpoint)
                    continue
                remaining = deadline - _now()
                if remaining <= 0:
                    break
                try:
                    elements = await asyncio.wait_for(
                        _one(client, endpoint),
                        timeout=min(remaining, _PER_ENDPOINT_TIMEOUT_S + 1.0),
                    )
                except asyncio.TimeoutError:
                    _breaker_record_failure(endpoint)
                    continue
                if elements:
                    return elements
    except Exception as exc:  # pragma: no cover — defensive only
        logger.warning("OSM Overpass: unexpected error: %s", exc)
    return []


# ══════════════════════════════════════════════════════════════════════════════
# Element parsing
# ══════════════════════════════════════════════════════════════════════════════

def _parse_elements(elements: List[Dict[str, Any]], intent: str) -> List[ProviderEntity]:
    """Convert raw Overpass elements → list of ProviderEntity."""
    out: List[ProviderEntity] = []
    seen_names: set = set()

    for el in elements:
        tags = el.get("tags") or {}
        name = (tags.get("name") or tags.get("name:en") or "").strip()
        if not name:
            continue
        name_key = name.lower()
        if name_key in seen_names:
            continue
        seen_names.add(name_key)

        lat, lon = _element_coords(el)
        if lat is None or lon is None:
            continue

        osm_type = el.get("type", "node")
        osm_id = el.get("id")
        source_url = f"https://www.openstreetmap.org/{osm_type}/{osm_id}" if osm_id else None

        rating = _safe_float(tags.get("stars"))
        if rating is not None:
            # OSM "stars" is 1..5 — same scale as our ratings.
            rating = max(0.0, min(5.0, rating))

        address = _build_address(tags)

        out.append(ProviderEntity(
            name=name,
            source="osm",
            source_id=f"{osm_type}/{osm_id}" if osm_id else None,
            source_url=source_url,
            latitude=lat,
            longitude=lon,
            address=address,
            city=tags.get("addr:city"),
            country=tags.get("addr:country"),
            category=_category_label(tags, intent),
            tags=_collect_feature_tags(tags),
            rating=rating,
            website=tags.get("website") or tags.get("contact:website"),
            phone=tags.get("phone") or tags.get("contact:phone"),
            hours=tags.get("opening_hours"),
            # OSM rarely has reviews; confidence reflects "structured but unrated".
            confidence=0.75,
        ))

    return out


def _element_coords(el: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    """Pull lat/lon out of a node (direct) or way/relation (`center`)."""
    if "lat" in el and "lon" in el:
        return _safe_float(el["lat"]), _safe_float(el["lon"])
    center = el.get("center") or {}
    return _safe_float(center.get("lat")), _safe_float(center.get("lon"))


def _build_address(tags: Dict[str, str]) -> Optional[str]:
    """Compose a single-line address from OSM addr:* tags."""
    parts = []
    house = tags.get("addr:housenumber")
    street = tags.get("addr:street")
    if house and street:
        parts.append(f"{house} {street}")
    elif street:
        parts.append(street)
    for k in ("addr:suburb", "addr:city", "addr:state", "addr:postcode", "addr:country"):
        v = tags.get(k)
        if v and v not in parts:
            parts.append(v)
    return ", ".join(parts) if parts else None


def _category_label(tags: Dict[str, str], intent: str) -> Optional[str]:
    """Pick the most descriptive OSM tag as a UI-friendly category."""
    for key in ("tourism", "amenity", "shop", "leisure", "historic", "cuisine"):
        if key in tags:
            return str(tags[key]).replace("_", " ").title()
    return intent.replace("_search", "").replace("_", " ").title()


def _collect_feature_tags(tags: Dict[str, str]) -> List[str]:
    """Surface the OSM tags most useful for embeddings (amenities, cuisine, …)."""
    out: List[str] = []
    for key in ("cuisine", "amenity", "tourism", "leisure", "shop", "historic"):
        v = tags.get(key)
        if v:
            out.append(str(v).replace("_", " "))
    # Boolean-ish amenity flags (wifi, wheelchair, outdoor_seating …)
    for k, v in tags.items():
        if isinstance(v, str) and v.lower() in {"yes", "free", "limited"} and ":" not in k:
            out.append(k.replace("_", " "))
    return out[:12]


def _safe_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Reshape to per-intent entity dict
# ══════════════════════════════════════════════════════════════════════════════

def _to_schema_dict(p: ProviderEntity, intent: str) -> Dict[str, Any]:
    """Convert a ProviderEntity into the dict shape the ranker / UI expects.

    Each intent maps onto a specific entity schema (HotelEntity, etc.). We
    write the dict directly rather than going through the Pydantic class to
    preserve provider-specific fields (`source`, `_distance_km` etc.) that
    the schema doesn't enumerate.
    """
    from . import provider_priority
    base: Dict[str, Any] = {
        "name": p.name,
        "latitude": p.latitude,
        "longitude": p.longitude,
        "address": p.address,
        "rating": p.rating,
        "website": p.website,
        "source": p.source,
        "source_url": p.source_url,
        "maps_url": _maps_url(p),
        "category": p.category,
        "type_label": p.category,
        "_trust": round(p.effective_trust(), 4),
        "_source_priority": provider_priority(p.source),
    }
    if p.hours:
        base["hours"] = p.hours
    if p.phone:
        base["phone"] = p.phone

    if intent == "hotel_search":
        base["type"] = "hotel"
        base["location"] = p.address or p.city
        base["amenities"] = p.tags
    elif intent == "restaurant_search":
        base["type"] = "restaurant"
        base["features"] = p.tags
        base["cuisine"] = next((t for t in p.tags if "cuisine" not in t.lower() and len(t) > 2), None)
    elif intent == "local_service":
        base["type"] = "local_business"
    elif intent == "place_search":
        base["type"] = "place"
        base["location"] = p.address or p.city
    elif intent == "event_search":
        base["type"] = "event"
        base["venue"] = p.name

    return {k: v for k, v in base.items() if v is not None and v != []}


def _maps_url(p: ProviderEntity) -> Optional[str]:
    if p.latitude is None or p.longitude is None:
        return None
    name = quote_plus(p.name)
    return (
        f"https://www.google.com/maps/search/?api=1"
        f"&query={name}&query_place_id=&"
        f"ll={p.latitude},{p.longitude}"
    )


def _build_sources(entities: List[ProviderEntity]) -> List[Dict[str, Any]]:
    """One ``sources`` entry per OSM-backed result so the UI cites them."""
    sources: List[Dict[str, Any]] = []
    seen: set = set()
    for e in entities:
        if not e.source_url or e.source_url in seen:
            continue
        seen.add(e.source_url)
        sources.append({
            "url": e.source_url,
            "title": e.name,
            "snippet": e.category or "OpenStreetMap entry",
        })
    return sources
