"""
Google Places nearby-entity provider (scaffold, env-key driven).

Activation
──────────
Reads ``GOOGLE_PLACES_API_KEY`` from the environment at call time.
When the key is absent, ``supports()`` returns False and the
multi-provider chain skips this backend entirely — no network calls,
no startup cost, no errors.

Drop a key into your .env (or shell) and Spark picks it up on the next
search. No code change needed.

Endpoint
────────
Uses the **legacy** Places Nearby Search REST endpoint:
  https://maps.googleapis.com/maps/api/place/nearbysearch/json
because it returns rating + user_ratings_total in one shot without the
field-mask complexity of the v1 API. Both share the same key.

Trust
─────
Per ``providers/__init__.py``, google_places is trust=0.95 and the
highest-priority provider — wins over OSM/Foursquare when present.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

import httpx

from .provider_models import ProviderEntity
from .provider_registry import (
    google_filter,
    supported_intents,
)

logger = logging.getLogger(__name__)

# ── Limits ───────────────────────────────────────────────────────────────────
_ENDPOINT = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
_REQUEST_TIMEOUT_S = 6.0
_GLOBAL_SEMAPHORE = asyncio.Semaphore(3)

# In-process TTL cache mirrors osm_provider's pattern. Google Places has a
# generous free tier but every call costs money once you cross it; caching
# 10 min of nearby lookups is cheap insurance.
_CACHE_TTL_S = 600.0
_CACHE_MAX_ENTRIES = 256
_cache: Dict[str, Tuple[float, List[Dict[str, Any]], List[Dict[str, Any]]]] = {}


def _now() -> float:
    import time
    return time.monotonic()


def _cache_key(intent: str, query: str, lat: float, lon: float, radius_km: float) -> str:
    import hashlib
    import re
    tokens = sorted(set(re.findall(r"[a-z0-9]+", query.lower())))
    payload = f"google|{intent}|{round(lat, 2)}|{round(lon, 2)}|{round(radius_km, 1)}|{','.join(tokens)}"
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


def _cache_put(key: str, entities: List[Dict[str, Any]], sources: List[Dict[str, Any]]) -> None:
    if len(_cache) >= _CACHE_MAX_ENTRIES:
        oldest = min(_cache.items(), key=lambda kv: kv[1][0])[0]
        _cache.pop(oldest, None)
    _cache[key] = (_now(), entities, sources)


# ══════════════════════════════════════════════════════════════════════════════
# Public interface
# ══════════════════════════════════════════════════════════════════════════════

def _api_key() -> Optional[str]:
    """Lazy env lookup so the provider activates the moment a key is set."""
    key = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
    return key or None


def supports(intent: str) -> bool:
    """Active only when both an API key is present and the intent is mapped."""
    if not _api_key():
        return False
    return intent in supported_intents()


async def search(
    intent: str,
    query: str,
    user_lat: float,
    user_lon: float,
    radius_km: float = 25.0,
    max_results: int = 25,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Nearby Search against Google Places.

    Returns ``(entities, sources)`` — empty on any failure. Caller is
    expected to fall through to the next provider in the chain.
    """
    key = _api_key()
    if not key:
        return [], []

    pf = await google_filter(intent, query)
    if pf is None or not pf.google_type:
        logger.debug("Google Places: no type mapping for intent=%s query=%r", intent, query)
        return [], []

    ckey = _cache_key(intent, query, user_lat, user_lon, radius_km)
    cached = _cache_get(ckey)
    if cached is not None:
        ents, srcs = cached
        logger.info("Google Places: cache hit (%d) for %s near (%.4f, %.4f)",
                    len(ents), intent, user_lat, user_lon)
        return ents[:max_results], srcs[:max_results]

    radius_m = int(max(500.0, min(radius_km * 1000.0, 50_000.0)))
    params = {
        "location": f"{user_lat},{user_lon}",
        "radius": str(radius_m),
        "type": pf.google_type,
        "key": key,
    }
    # Optional refinement (events get "event" keyword; intent-derived queries)
    if pf.google_keyword:
        params["keyword"] = pf.google_keyword

    async with _GLOBAL_SEMAPHORE:
        results = await _http_call(params)

    if not results:
        return [], []

    provider_entities = _parse_results(results, intent)[:max_results]
    entities = [_to_schema_dict(p, intent) for p in provider_entities]
    sources = _build_sources(provider_entities)
    _cache_put(ckey, entities, sources)
    logger.info(
        "Google Places: %d %s entities within %dm of (%.4f, %.4f)",
        len(entities), intent, radius_m, user_lat, user_lon,
    )
    return entities, sources


# ══════════════════════════════════════════════════════════════════════════════
# HTTP
# ══════════════════════════════════════════════════════════════════════════════

async def _http_call(params: Dict[str, str]) -> List[Dict[str, Any]]:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(_ENDPOINT, params=params, timeout=_REQUEST_TIMEOUT_S)
        if resp.status_code != 200:
            logger.warning("Google Places: HTTP %d — %s", resp.status_code, resp.text[:200])
            return []
        body = resp.json()
        status = body.get("status", "")
        if status not in ("OK", "ZERO_RESULTS"):
            logger.warning("Google Places: API status=%s msg=%s",
                           status, body.get("error_message", "")[:200])
            return []
        return body.get("results") or []
    except asyncio.TimeoutError:
        logger.warning("Google Places: request timed out")
        return []
    except Exception as exc:
        logger.warning("Google Places: request failed: %s", exc)
        return []


# ══════════════════════════════════════════════════════════════════════════════
# Result parsing
# ══════════════════════════════════════════════════════════════════════════════

def _parse_results(results: List[Dict[str, Any]], intent: str) -> List[ProviderEntity]:
    out: List[ProviderEntity] = []
    seen: set = set()

    for r in results:
        name = (r.get("name") or "").strip()
        if not name:
            continue
        nk = name.lower()
        if nk in seen:
            continue
        seen.add(nk)

        geometry = (r.get("geometry") or {}).get("location") or {}
        lat = _safe_float(geometry.get("lat"))
        lon = _safe_float(geometry.get("lng"))
        if lat is None or lon is None:
            continue

        place_id = r.get("place_id") or ""
        source_url = (
            f"https://www.google.com/maps/place/?q=place_id:{place_id}"
            if place_id else None
        )

        # Google rating already on 0..5; user_ratings_total is integer.
        rating = _safe_float(r.get("rating"))
        review_count = r.get("user_ratings_total")

        # Price level: Google uses 0..4. Keep as-is so the ranker price term
        # is comparable across providers.
        price_level = r.get("price_level")

        category = ", ".join(r.get("types", [])[:2]).replace("_", " ").title() or None

        out.append(ProviderEntity(
            name=name,
            source="google_places",
            source_id=place_id or None,
            source_url=source_url,
            latitude=lat,
            longitude=lon,
            address=r.get("vicinity"),
            category=category,
            tags=[t.replace("_", " ") for t in r.get("types", [])[:6]],
            rating=rating,
            review_count=int(review_count) if isinstance(review_count, (int, float)) else None,
            price_level=int(price_level) if isinstance(price_level, (int, float)) else None,
            confidence=0.9 if rating is not None else 0.7,
        ))
    return out


# ══════════════════════════════════════════════════════════════════════════════
# Reshape
# ══════════════════════════════════════════════════════════════════════════════

def _to_schema_dict(p: ProviderEntity, intent: str) -> Dict[str, Any]:
    from . import provider_priority

    base: Dict[str, Any] = {
        "name": p.name,
        "latitude": p.latitude,
        "longitude": p.longitude,
        "address": p.address,
        "rating": p.rating,
        "review_count": p.review_count,
        "source": p.source,
        "source_url": p.source_url,
        "maps_url": _maps_url(p),
        "category": p.category,
        "type_label": p.category,
        "_trust": round(p.effective_trust(), 4),
        "_source_priority": provider_priority(p.source),
    }

    if intent == "hotel_search":
        base["type"] = "hotel"
        base["location"] = p.address
        base["amenities"] = p.tags
    elif intent == "restaurant_search":
        base["type"] = "restaurant"
        base["features"] = p.tags
        if p.price_level is not None:
            base["price_range"] = "$" * max(1, min(4, p.price_level))
    elif intent == "local_service":
        base["type"] = "local_business"
    elif intent == "place_search":
        base["type"] = "place"
        base["location"] = p.address
    elif intent == "event_search":
        base["type"] = "event"
        base["venue"] = p.name

    return {k: v for k, v in base.items() if v is not None and v != []}


def _maps_url(p: ProviderEntity) -> Optional[str]:
    if p.source_id:
        return f"https://www.google.com/maps/place/?q=place_id:{p.source_id}"
    if p.latitude is None or p.longitude is None:
        return None
    name = quote_plus(p.name)
    return (
        f"https://www.google.com/maps/search/?api=1"
        f"&query={name}&ll={p.latitude},{p.longitude}"
    )


def _build_sources(entities: List[ProviderEntity]) -> List[Dict[str, Any]]:
    sources: List[Dict[str, Any]] = []
    seen: set = set()
    for e in entities:
        if not e.source_url or e.source_url in seen:
            continue
        seen.add(e.source_url)
        sources.append({
            "url": e.source_url,
            "title": e.name,
            "snippet": e.category or "Google Places entry",
        })
    return sources


def _safe_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
