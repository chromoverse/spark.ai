"""
Query Geo Resolver — turn place mentions in a query into coordinates.

Why this exists
───────────────
The previous architecture treated geography as a *phrase pattern*
("near me" only). That made "hotels in Mumbai", "cafes around Pokhara",
and "restaurants in Tokyo" silently bypass the structured retrieval
substrate — they fell straight to DDGS + LLM-extract because no coords
were ever resolved.

This module makes geography *coordinate-native* instead of phrase-native.

Pipeline
────────
  query
    → strip intent-nouns (hotel, restaurant, cafe…) + stopwords (in, near…)
    → residue is the candidate place name
    → Nominatim forward-geocode
    → {lat, lon, city, country, display_name}
    → cached aggressively (cities don't move)

Hardening (mirrors osm_provider.py)
───────────────────────────────────
  • Global semaphore — public Nominatim is shared infra.
  • Per-call timeout + total deadline.
  • Circuit breaker per mirror.
  • 24h TTL cache on positive results; 5min on negative (place name
    might be a typo the user fixes).
  • User-Agent identifying Spark — Nominatim ACL requires it.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)


# ── Public type ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GeoLocation:
    lat: float
    lon: float
    city: Optional[str]
    country: Optional[str]
    display_name: str            # what Nominatim called it (good for logging)
    source: str = "nominatim"


# ── Stopwords for candidate extraction ───────────────────────────────────────
# Categories of words we strip before sending to Nominatim:
#   • Intent nouns (hotel, restaurant, cafe…) — what we're searching for,
#     never the place itself.
#   • Prepositions and locator words ("in", "at", "near", "around"…).
#   • Common modifiers ("best", "top", "cheap"…).
#
# Keep this list tight. Stripping too much will swallow real place names
# (e.g. "Bay Area" if "bay" leaks in here). The bias is toward leaving
# *more* in the residue and letting Nominatim do the disambiguation.

_INTENT_NOUNS = {
    "hotel", "hotels", "hostel", "hostels", "motel", "motels",
    "restaurant", "restaurants", "cafe", "cafes", "café", "cafés",
    "bar", "bars", "pub", "pubs", "bistro",
    "hospital", "hospitals", "clinic", "clinics", "pharmacy", "pharmacies",
    "chemist", "chemists", "drugstore", "dentist", "dentists",
    "gym", "gyms", "fitness", "yoga", "spa", "spas",
    "bank", "banks", "atm", "atms",
    "school", "schools", "college", "colleges", "university", "universities",
    "library", "libraries", "museum", "museums",
    "place", "places", "thing", "things", "spot", "spots",
    "attraction", "attractions", "landmark", "landmarks",
    "event", "events", "concert", "concerts", "festival", "festivals",
    "shop", "shops", "store", "stores", "market", "markets",
    "salon", "salons", "barber", "barbers",
    "stop", "stops", "station", "stations",   # ambiguous — "bus station Mumbai"
    "movie", "movies", "cinema", "cinemas", "theater", "theaters", "theatre", "theatres",
}

_PREPOSITIONS = {
    "in", "at", "around", "near", "by", "within", "inside", "across",
    "from", "to", "of", "the", "a", "an",
}

_MODIFIERS = {
    "best", "top", "good", "great", "cheap", "cheapest", "budget",
    "luxury", "fancy", "nearby", "close", "open", "now", "today",
    "tonight", "tomorrow", "this", "weekend",
    "show", "find", "list", "search", "give", "get", "tell", "me",
    "where", "what", "which", "are", "is", "some",
    "to", "for", "with",
    # Verbs that appear in "things to X in <place>" patterns. Real place
    # names rarely contain these as standalone tokens, so stripping is safe.
    "do", "visit", "see", "eat", "drink", "stay", "go", "try", "check",
    "explore", "experience", "sleep", "work", "study", "live", "meet",
    "buy", "watch", "play", "book", "rent", "hire",
    # explicit "near me" / "around me" — handled separately by current_location
    "my", "us",
}

_STOPWORDS = _INTENT_NOUNS | _PREPOSITIONS | _MODIFIERS

_TOKEN_RE = re.compile(r"[\wÀ-ÿ]+", re.UNICODE)


# ── Candidate extraction ─────────────────────────────────────────────────────

def extract_place_candidate(query: str) -> Optional[str]:
    """Pull the candidate place name out of a query.

    Strips known intent-nouns, prepositions, and modifiers. The remaining
    tokens (joined with spaces) form the place candidate. Returns None
    when nothing usable is left.

    Examples (informal — see tests for the locked behaviour):
      "hotels in Mumbai"             → "Mumbai"
      "best restaurants in Tokyo"    → "Tokyo"
      "cafes around Pokhara"         → "Pokhara"
      "things to do in New York"     → "New York"
      "near me hotels"               → None     (handled by current_location)
      "hospitals"                    → None     (no place hint)
    """
    if not query:
        return None

    # Explicit "near me" / "nearby" → bail; current_location owns this case.
    lowered = query.lower()
    if re.search(r"\bnear\s+(?:me|my\s+\w+)\b", lowered) or re.search(r"\bnearby\b", lowered):
        return None

    tokens = _TOKEN_RE.findall(query)
    keep = [t for t in tokens if t.lower() not in _STOPWORDS]
    if not keep:
        return None

    candidate = " ".join(keep).strip()
    # Two-character residues are almost always noise ("ny" → would geocode to
    # something random). Require at least three chars or a multi-token name.
    if len(candidate) < 3 and " " not in candidate:
        return None
    return candidate


# ── Nominatim client + caching + breaker ─────────────────────────────────────

_ENDPOINT = "https://nominatim.openstreetmap.org/search"
_REQUEST_TIMEOUT_S = 4.0
_TOTAL_TIMEOUT_S = 5.0
_GLOBAL_SEMAPHORE = asyncio.Semaphore(2)

_POSITIVE_TTL_S = 24 * 60 * 60     # 24 hours — cities don't move.
_NEGATIVE_TTL_S = 5 * 60           # 5 minutes — user might be retyping a typo.
_CACHE_MAX_ENTRIES = 1024
_cache: Dict[str, Tuple[float, Optional[GeoLocation]]] = {}

_BREAKER_FAIL_THRESHOLD = 3
_BREAKER_COOLDOWN_S = 120.0
_breaker_state = {"fails": 0, "open_until": 0.0}

_HEADERS = {
    # Nominatim requires a descriptive User-Agent identifying the application.
    "User-Agent": "SparkAI/1.0 (https://github.com/SiddTheCoder) geo_resolver",
    "Accept": "application/json",
    "Accept-Language": os.environ.get("SPARK_GEO_LANG", "en"),
}


def _now() -> float:
    return time.monotonic()


def _cache_key(place: str) -> str:
    return hashlib.sha1(place.strip().lower().encode("utf-8")).hexdigest()


def _cache_get(key: str) -> Tuple[bool, Optional[GeoLocation]]:
    """Returns (hit, value). hit=True means we have a cached answer (incl. None)."""
    entry = _cache.get(key)
    if entry is None:
        return False, None
    ts, value = entry
    ttl = _POSITIVE_TTL_S if value is not None else _NEGATIVE_TTL_S
    if _now() - ts > ttl:
        _cache.pop(key, None)
        return False, None
    return True, value


def _cache_put(key: str, value: Optional[GeoLocation]) -> None:
    if len(_cache) >= _CACHE_MAX_ENTRIES:
        # Evict oldest. Linear scan acceptable at this size.
        oldest = min(_cache.items(), key=lambda kv: kv[1][0])[0]
        _cache.pop(oldest, None)
    _cache[key] = (_now(), value)


def _breaker_open() -> bool:
    return _breaker_state["open_until"] > _now()


def _breaker_record_failure() -> None:
    _breaker_state["fails"] += 1
    if _breaker_state["fails"] >= _BREAKER_FAIL_THRESHOLD:
        _breaker_state["open_until"] = _now() + _BREAKER_COOLDOWN_S
        logger.warning(
            "geo_resolver: Nominatim circuit OPEN (fails=%d, cooldown=%.0fs)",
            _breaker_state["fails"], _BREAKER_COOLDOWN_S,
        )


def _breaker_record_success() -> None:
    _breaker_state["fails"] = 0
    _breaker_state["open_until"] = 0.0


# ── Core ─────────────────────────────────────────────────────────────────────

async def geocode_place(place: str) -> Optional[GeoLocation]:
    """Forward-geocode a place string. Cached. Returns None on miss/failure."""
    if not place or not place.strip():
        return None

    key = _cache_key(place)
    hit, value = _cache_get(key)
    if hit:
        logger.debug("geo_resolver: cache %s for %r", "hit" if value else "neg-hit", place)
        return value

    if _breaker_open():
        logger.debug("geo_resolver: skipping %r — circuit open", place)
        return None

    params = {
        "q": place,
        "format": "json",
        "limit": "1",
        "addressdetails": "1",
    }

    deadline = _now() + _TOTAL_TIMEOUT_S
    async with _GLOBAL_SEMAPHORE:
        try:
            remaining = deadline - _now()
            if remaining <= 0:
                return None
            async with httpx.AsyncClient(headers=_HEADERS) as client:
                resp = await asyncio.wait_for(
                    client.get(_ENDPOINT, params=params, timeout=_REQUEST_TIMEOUT_S),
                    timeout=min(remaining, _REQUEST_TIMEOUT_S + 0.5),
                )
        except (asyncio.TimeoutError, httpx.RequestError) as exc:
            logger.info("geo_resolver: network failure for %r: %s", place, exc)
            _breaker_record_failure()
            return None
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("geo_resolver: unexpected error: %s", exc)
            _breaker_record_failure()
            return None

    if resp.status_code != 200:
        logger.info("geo_resolver: HTTP %d for %r", resp.status_code, place)
        _breaker_record_failure()
        _cache_put(key, None)
        return None

    _breaker_record_success()

    try:
        results = resp.json()
    except Exception:
        _cache_put(key, None)
        return None

    if not results:
        _cache_put(key, None)
        return None

    item = results[0]
    lat = _safe_float(item.get("lat"))
    lon = _safe_float(item.get("lon"))
    if lat is None or lon is None:
        _cache_put(key, None)
        return None

    addr = item.get("address") or {}
    location = GeoLocation(
        lat=lat,
        lon=lon,
        city=addr.get("city") or addr.get("town") or addr.get("village") or addr.get("hamlet"),
        country=addr.get("country"),
        display_name=str(item.get("display_name") or place),
    )
    _cache_put(key, location)
    logger.info(
        "geo_resolver: %r → (%.4f, %.4f) %s",
        place, location.lat, location.lon, location.display_name,
    )
    return location


async def resolve_query_geo(query: str) -> Optional[GeoLocation]:
    """End-to-end: query string → GeoLocation. Returns None when no place
    can be extracted or the geocoder can't resolve it."""
    candidate = extract_place_candidate(query)
    if not candidate:
        return None
    return await geocode_place(candidate)


async def reverse_geocode(lat: float, lon: float) -> Optional[GeoLocation]:
    """Reverse-geocode lat/lon coordinates to a GeoLocation object. Cached."""
    # Round to 4 decimal places (~11m accuracy) for caching efficiency
    key = f"rev_{lat:.4f}_{lon:.4f}"
    hit, value = _cache_get(key)
    if hit:
        logger.debug("geo_resolver: reverse cache hit for (%.4f, %.4f)", lat, lon)
        return value

    if _breaker_open():
        logger.debug("geo_resolver: skipping reverse (%.4f, %.4f) — circuit open", lat, lon)
        return None

    params = {
        "lat": str(lat),
        "lon": str(lon),
        "format": "json",
        "addressdetails": "1",
    }

    deadline = _now() + _TOTAL_TIMEOUT_S
    async with _GLOBAL_SEMAPHORE:
        try:
            remaining = deadline - _now()
            if remaining <= 0:
                return None
            async with httpx.AsyncClient(headers=_HEADERS) as client:
                resp = await asyncio.wait_for(
                    client.get("https://nominatim.openstreetmap.org/reverse", params=params, timeout=_REQUEST_TIMEOUT_S),
                    timeout=min(remaining, _REQUEST_TIMEOUT_S + 0.5),
                )
        except (asyncio.TimeoutError, httpx.RequestError) as exc:
            logger.info("geo_resolver: reverse geocode network failure for (%.4f, %.4f): %s", lat, lon, exc)
            _breaker_record_failure()
            return None
        except Exception as exc:
            logger.warning("geo_resolver: unexpected reverse geocode error: %s", exc)
            _breaker_record_failure()
            return None

    if resp.status_code != 200:
        logger.info("geo_resolver: HTTP %d for reverse (%.4f, %.4f)", resp.status_code, lat, lon)
        _breaker_record_failure()
        _cache_put(key, None)
        return None

    _breaker_record_success()

    try:
        item = resp.json()
    except Exception:
        _cache_put(key, None)
        return None

    if not item or "error" in item:
        _cache_put(key, None)
        return None

    addr = item.get("address") or {}
    location = GeoLocation(
        lat=lat,
        lon=lon,
        city=addr.get("city") or addr.get("town") or addr.get("village") or addr.get("hamlet"),
        country=addr.get("country"),
        display_name=str(item.get("display_name") or f"{lat},{lon}"),
    )
    _cache_put(key, location)
    logger.info(
        "geo_resolver: reverse (%.4f, %.4f) → %s",
        lat, lon, location.display_name,
    )
    return location


def _safe_float(value: Any) -> Optional[float]:
    import math as _math
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not _math.isfinite(result):
        return None
    return result
