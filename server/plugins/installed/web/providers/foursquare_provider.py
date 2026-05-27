"""
Foursquare Places v3 nearby-entity provider (scaffold, env-key driven).

Activation
──────────
Reads ``FOURSQUARE_API_KEY`` from the environment at call time. When the
key is absent, ``supports()`` returns False and the multi-provider chain
skips this backend entirely.

Foursquare's developer tier is free and generous for an interactive
assistant — sign up at https://foursquare.com/developers/, create a
project, copy the API key into your .env, and Spark picks it up.

Endpoint
────────
  GET https://api.foursquare.com/v3/places/search
  Authorization: <api-key>

Trust
─────
Per ``providers/__init__.py``, foursquare is trust=0.90 and runs after
Google Places, before OSM.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

import httpx

from .provider_models import ProviderEntity
from .provider_registry import foursquare_filter, supported_intents

logger = logging.getLogger(__name__)

# ── Limits ───────────────────────────────────────────────────────────────────
_ENDPOINT = "https://api.foursquare.com/v3/places/search"
_REQUEST_TIMEOUT_S = 6.0
_GLOBAL_SEMAPHORE = asyncio.Semaphore(3)

_CACHE_TTL_S = 600.0
_CACHE_MAX_ENTRIES = 256
_cache: Dict[str, Tuple[float, List[Dict[str, Any]], List[Dict[str, Any]]]] = {}


def _now() -> float:
    import time
    return time.monotonic()


def _cache_key(intent: str, query: str, lat: Optional[float], lon: Optional[float], radius_km: float) -> str:
    import hashlib
    import re
    tokens = sorted(set(re.findall(r"[a-z0-9]+", query.lower())))
    lat_val = round(lat, 2) if lat is not None else "None"
    lon_val = round(lon, 2) if lon is not None else "None"
    payload = f"fsq|{intent}|{lat_val}|{lon_val}|{round(radius_km, 1)}|{','.join(tokens)}"
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
    key = os.environ.get("FOURSQUARE_API_KEY", "").strip()
    return key or None


def supports(intent: str) -> bool:
    if not _api_key():
        return False
    return intent in supported_intents()


async def search(
    intent: str,
    query: str,
    user_lat: Optional[float] = None,
    user_lon: Optional[float] = None,
    radius_km: float = 25.0,
    max_results: int = 25,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    key = _api_key()
    if not key:
        return [], []

    if user_lat is None or user_lon is None:
        logger.debug("Foursquare: missing coordinates (lat=%s, lon=%s) - returning empty", user_lat, user_lon)
        return [], []

    pf = await foursquare_filter(intent, query)
    if pf is None:
        logger.debug("Foursquare: no filter mapping for intent=%s query=%r", intent, query)
        return [], []

    ckey = _cache_key(intent, query, user_lat, user_lon, radius_km)
    cached = _cache_get(ckey)
    if cached is not None:
        ents, srcs = cached
        logger.info("Foursquare: cache hit (%d) for %s near (%.4f, %.4f)",
                    len(ents), intent, user_lat, user_lon)
        return ents[:max_results], srcs[:max_results]

    radius_m = int(max(500.0, min(radius_km * 1000.0, 50_000.0)))
    params: Dict[str, str] = {
        "ll": f"{user_lat},{user_lon}",
        "radius": str(radius_m),
        "limit": str(min(max(max_results, 1), 50)),
        "sort": "RELEVANCE",
        # Ask for the fields we actually consume — Foursquare bills per-field
        # in the long run and we only need a fixed subset.
        "fields": "fsq_id,name,location,geocodes,categories,rating,price,distance,website,tel,hours",
    }
    if pf.foursquare_categories:
        params["categories"] = ",".join(pf.foursquare_categories)
    if pf.foursquare_query:
        params["query"] = pf.foursquare_query

    headers = {"Authorization": key, "Accept": "application/json"}

    async with _GLOBAL_SEMAPHORE:
        results = await _http_call(params, headers)

    if not results:
        return [], []

    provider_entities = _parse_results(results, intent)[:max_results]
    entities = [_to_schema_dict(p, intent) for p in provider_entities]
    sources = _build_sources(provider_entities)
    _cache_put(ckey, entities, sources)
    logger.info(
        "Foursquare: %d %s entities within %dm of (%.4f, %.4f)",
        len(entities), intent, radius_m, user_lat, user_lon,
    )
    return entities, sources


# ══════════════════════════════════════════════════════════════════════════════
# HTTP
# ══════════════════════════════════════════════════════════════════════════════

async def _http_call(params: Dict[str, str], headers: Dict[str, str]) -> List[Dict[str, Any]]:
    try:
        async with httpx.AsyncClient(headers=headers) as client:
            resp = await client.get(_ENDPOINT, params=params, timeout=_REQUEST_TIMEOUT_S)
        if resp.status_code != 200:
            logger.warning("Foursquare: HTTP %d — %s", resp.status_code, resp.text[:200])
            return []
        body = resp.json()
        return body.get("results") or []
    except asyncio.TimeoutError:
        logger.warning("Foursquare: request timed out")
        return []
    except Exception as exc:
        logger.warning("Foursquare: request failed: %s", exc)
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

        # Foursquare puts coords under "geocodes.main" (lat/lng).
        geocodes = r.get("geocodes") or {}
        main = geocodes.get("main") or {}
        lat = _safe_float(main.get("latitude"))
        lon = _safe_float(main.get("longitude"))
        if lat is None or lon is None:
            continue

        fsq_id = r.get("fsq_id") or ""
        source_url = f"https://foursquare.com/v/{fsq_id}" if fsq_id else None

        # Foursquare rating is 0..10 → normalize to 0..5 for cross-provider parity.
        raw_rating = _safe_float(r.get("rating"))
        rating = round(raw_rating / 2.0, 2) if raw_rating is not None else None

        loc = r.get("location") or {}
        address = loc.get("formatted_address") or loc.get("address")

        categories = r.get("categories") or []
        cat_names = [c.get("name") for c in categories if c.get("name")]
        category = cat_names[0] if cat_names else None

        price_level = _safe_float(r.get("price"))  # FSQ uses 1..4

        out.append(ProviderEntity(
            name=name,
            source="foursquare",
            source_id=fsq_id or None,
            source_url=source_url,
            latitude=lat,
            longitude=lon,
            address=address,
            city=loc.get("locality"),
            country=loc.get("country"),
            category=category,
            tags=cat_names[:6],
            rating=rating,
            price_level=int(price_level) if price_level is not None else None,
            website=r.get("website"),
            phone=r.get("tel"),
            confidence=0.85 if rating is not None else 0.7,
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
        "website": p.website,
        "phone": p.phone,
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
            "snippet": e.category or "Foursquare entry",
        })
    return sources


def _safe_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
