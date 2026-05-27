"""
Multi-factor entity ranker — semantic-aware, geo-aware.

Scoring (weights sum to 1.0):
  hotel:          semantic 0.35 | rating 0.20 | review 0.15 | price 0.15 | geo 0.15
  restaurant:     semantic 0.40 | rating 0.25 | review 0.15 | geo 0.20
  local_business: semantic 0.40 | rating 0.30 | review 0.15 | geo 0.15
  place:          semantic 0.40 | rating 0.25 | review 0.15 | geo 0.20
  event:          semantic 0.35 | rating 0.20 | review 0.15 | price 0.10 | geo 0.20
  product:        semantic 0.40 | rating 0.25 | review 0.15 | price 0.20         (no geo)
  movie:          semantic 0.45 | rating 0.35 | review 0.20                      (no geo)
  person:         semantic 0.70 | rating 0.30                                    (no geo)
  college:        semantic 0.40 | rating 0.30 | review 0.20 | geo 0.10
  flight:         price 0.50 | semantic 0.30 | rating 0.20                       (no geo)

Geo behaviour
─────────────
If the caller provides user coords AND the entity has coords:
  • Compute haversine distance.
  • HARD DISCARD if distance > max_radius_km (when supplied).
  • Otherwise contribute geo = 1 - (distance / max_radius_km).

If either coord side is missing, the geo term contributes 0 (neutral) — never
inflates a result that lacks geographic confirmation.

Semantic behaviour
──────────────────
One batched BGE-M3 call (server's existing `embedding_service`): query +
all entity text representations → cosine similarity per entity. Falls back
to keyword overlap if embedding generation fails (offline, model not
loaded, etc.) so the tool never breaks.
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


_WEIGHTS: Dict[str, Dict[str, float]] = {
    "hotel": {
        "semantic":     0.35,
        "rating":       0.20,
        "review_count": 0.15,
        "price":        0.15,
        "geo":          0.15,
    },
    "product": {
        "semantic":     0.40,
        "rating":       0.25,
        "review_count": 0.15,
        "price":        0.20,
    },
    "restaurant": {
        "semantic":     0.40,
        "rating":       0.25,
        "review_count": 0.15,
        "geo":          0.20,
    },
    "local_business": {
        "semantic":     0.40,
        "rating":       0.30,
        "review_count": 0.15,
        "geo":          0.15,
    },
    "person": {
        "semantic": 0.70,
        "rating":   0.30,
    },
    "movie": {
        "semantic":     0.45,
        "rating":       0.35,
        "review_count": 0.20,
    },
    "event": {
        "semantic":     0.35,
        "rating":       0.20,
        "review_count": 0.15,
        "price":        0.10,
        "geo":          0.20,
    },
    "college": {
        "semantic":     0.40,
        "rating":       0.30,
        "review_count": 0.20,
        "geo":          0.10,
    },
    "place": {
        "semantic":     0.40,
        "rating":       0.25,
        "review_count": 0.15,
        "geo":          0.20,
    },
    "flight": {
        "semantic": 0.30,
        "price":    0.50,
        "rating":   0.20,
    },
}

_DEFAULT_WEIGHTS = {"semantic": 0.5, "rating": 0.3, "review_count": 0.2}

_EARTH_RADIUS_KM = 6371.0088

# Multiplier applied to the final score when a coordless entity fails the
# city-name soft check. Strong demotion (≈ -65%) — enough that a 5-star
# wrong-city entity loses to a 3-star right-city one — but not a hard discard.
_WRONG_CITY_PENALTY = 0.35


def _entity_mentions_city(entity: Dict[str, Any], city_token: str) -> bool:
    """True iff the entity's textual fields mention ``city_token``.

    Checks name, address, location, and description as a single lowercased
    haystack. Uses substring match so 'kathmandu' inside 'Kathmandu Valley'
    or 'New York City' inside 'New York' counts. ``city_token`` is expected
    already-lowercased by the caller.
    """
    if not city_token:
        return True
    fields = (
        entity.get("name"),
        entity.get("address"),
        entity.get("location"),
        entity.get("description"),
    )
    haystack = " ".join(str(f) for f in fields if f).lower()
    return city_token in haystack


async def rank_entities(
    entities: List[Dict[str, Any]],
    entity_schema: str,
    query: str,
    *,
    user_lat: Optional[float] = None,
    user_lon: Optional[float] = None,
    max_radius_km: Optional[float] = None,
    user_city: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Score and sort entities descending. Returns the surviving entities with
    ``_score`` injected (and ``_distance_km`` for geo-aware schemas).

    Geo hard filter: when both user coords and entity coords exist, entities
    farther than ``max_radius_km`` are discarded outright. Entities missing
    coords are kept (the LLM-extraction path often lacks them) but receive
    a zero ``geo`` contribution.

    City-name soft filter: when ``user_city`` is provided and an entity
    has NO coords, the entity's text representation must mention the city.
    If not, its final score is multiplied by ``_WRONG_CITY_PENALTY`` so it
    cannot outrank a coord-confirmed or city-matched entity. Closes the
    LLM-extraction hallucination leak (where a Miami hotel surfaces for a
    Kathmandu query because the LLM extracted it without coords).
    """
    if not entities:
        return []

    weights = _WEIGHTS.get(entity_schema, _DEFAULT_WEIGHTS)
    geo_enabled = (
        "geo" in weights
        and user_lat is not None
        and user_lon is not None
    )

    city_token = (user_city or "").strip().lower() if "geo" in weights else ""

    # ── Geo hard filter + city-name soft flag ─────────────────────────────────
    survivors: List[Dict[str, Any]] = []
    for entity in entities:
        lat = _safe_float(entity.get("latitude"))
        lon = _safe_float(entity.get("longitude"))
        if geo_enabled and lat is not None and lon is not None:
            assert user_lat is not None and user_lon is not None
            dist_km = _haversine_km(user_lat, user_lon, lat, lon)
            entity["_distance_km"] = round(dist_km, 3)
            if max_radius_km and dist_km > max_radius_km:
                logger.debug(
                    "ranker: discarding %r — %.1fkm > %.1fkm radius",
                    entity.get("name"), dist_km, max_radius_km,
                )
                continue
            # Has coords + survived radius → city verified. No soft penalty.
            entity["_city_verified"] = True
        elif city_token:
            # Coord-less: rely on the city soft filter. Flag if entity text
            # doesn't mention the city; the score multiplier is applied later.
            if not _entity_mentions_city(entity, city_token):
                entity["_wrong_city_suspect"] = True
        survivors.append(entity)

    if not survivors:
        logger.info("ranker: all %d entities filtered out by geo radius", len(entities))
        return []

    # ── Semantic similarity (batched) ─────────────────────────────────────────
    semantic_scores = await _compute_semantic_scores(query, survivors, entity_schema)

    # ── Per-factor normalization ──────────────────────────────────────────────
    ratings = [_safe_float(e.get("rating")) or 0.0 for e in survivors]
    reviews = [int(_safe_float(e.get("review_count")) or 0) for e in survivors]
    prices  = [_extract_price(e) for e in survivors]

    max_rating  = max(ratings) if any(r > 0 for r in ratings) else 5.0
    max_reviews = max(reviews) if any(r > 0 for r in reviews) else 1
    valid_prices = [p for p in prices if p > 0]
    min_price = min(valid_prices) if valid_prices else 0.0
    max_price = max(valid_prices) if valid_prices else 1.0

    # ── Score each survivor ───────────────────────────────────────────────────
    for idx, entity in enumerate(survivors):
        score = 0.0

        if "semantic" in weights:
            score += weights["semantic"] * semantic_scores[idx]

        if "rating" in weights and max_rating > 0:
            score += weights["rating"] * (ratings[idx] / max_rating)

        if "review_count" in weights and max_reviews > 0:
            score += weights["review_count"] * (reviews[idx] / max_reviews)

        if "price" in weights:
            price = prices[idx]
            if price > 0 and max_price > min_price:
                norm = 1.0 - (price - min_price) / (max_price - min_price)
                score += weights["price"] * norm
            elif price == 0:
                score += weights["price"] * 0.5

        if "geo" in weights:
            dist = entity.get("_distance_km")
            if geo_enabled and dist is not None and max_radius_km:
                # Closer = higher score; cap at 0 outside radius.
                proximity = max(0.0, 1.0 - dist / max_radius_km)
                score += weights["geo"] * proximity
            # If geo not resolvable, contribute 0 — never inflate unconfirmed entities.

        # Source-trust gentle tie-breaker. Multiplicative on (1 + small adjust)
        # so a high-trust provider barely edges out a low-trust one when the
        # other factors are equal — but it never compensates for a worse rating
        # or worse geo match.
        trust = _safe_float(entity.get("_trust"))
        if trust is not None:
            score *= 1.0 + 0.05 * (trust - 0.5)  # +2.5% to -2.5% nudge

        # City soft filter: coordless entity, user city known, no mention.
        # Strong demotion (NOT discard) — keeps the result available if it's
        # the only thing we have, but cannot outrank a verified city match.
        if entity.get("_wrong_city_suspect"):
            score *= _WRONG_CITY_PENALTY

        entity["_score"] = round(score, 4)

    survivors.sort(key=lambda e: e["_score"], reverse=True)
    return survivors


# ── Semantic scoring ─────────────────────────────────────────────────────────

async def _compute_semantic_scores(
    query: str,
    entities: List[Dict[str, Any]],
    entity_schema: str,
) -> List[float]:
    """
    One batched embedding call. Returns one cosine similarity per entity in
    the same order. Falls back to keyword overlap on any failure so a missing
    model never wedges the whole pipeline.
    """
    if not entities or not query.strip():
        return [0.0] * len(entities)

    entity_texts = [_entity_text(e, entity_schema) for e in entities]

    try:
        from app.ml import get_embeddings  # local import keeps this module cheap to load
        embeddings = await get_embeddings([query] + entity_texts)
        if not embeddings or len(embeddings) != len(entities) + 1:
            raise ValueError("embedding batch size mismatch")
        arr = np.array(embeddings, dtype=np.float32)
        q_vec = arr[0]
        e_vecs = arr[1:]
        # bge-m3 returns normalized vectors by default, but normalize defensively.
        q_norm = np.linalg.norm(q_vec) or 1.0
        e_norms = np.linalg.norm(e_vecs, axis=1)
        e_norms = np.where(e_norms == 0, 1.0, e_norms)
        cosines = (e_vecs @ q_vec) / (e_norms * q_norm)
        # Cosine on bge-m3 ranges roughly [-0.2, 1.0]; squash to [0, 1].
        return [float(max(0.0, min(1.0, c))) for c in cosines]
    except Exception as exc:
        logger.info(
            "ranker: semantic embedding unavailable (%s) — falling back to keyword overlap",
            exc,
        )
        return [_keyword_overlap(query, t) for t in entity_texts]


def _entity_text(entity: Dict[str, Any], entity_schema: str) -> str:
    """Build a short, content-rich representation of an entity for embedding."""
    parts: List[str] = []
    name = str(entity.get("name") or "").strip()
    if name:
        parts.append(name)

    # Generic content fields, schema-aware.
    for key in (
        "description", "category", "type_label",
        "cuisine", "price_range",
        "address", "location",
        "amenities", "features", "programs",
        "bio", "known_for",
        "plot", "genre",
    ):
        val = entity.get(key)
        if not val:
            continue
        if isinstance(val, list):
            parts.append(", ".join(str(v) for v in val[:8]))
        else:
            parts.append(str(val))

    if not parts:
        parts.append(entity_schema)
    return " — ".join(parts)[:600]


def _keyword_overlap(query: str, text: str) -> float:
    """Cheap keyword-overlap relevance for embedding-fallback."""
    q_words = set(re.findall(r"\w+", query.lower()))
    if not q_words:
        return 0.0
    t_words = set(re.findall(r"\w+", text.lower()))
    return len(q_words & t_words) / len(q_words)


# ── Geo helpers ──────────────────────────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two (lat, lon) pairs in degrees."""
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = rlat2 - rlat1
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _safe_float(value: Any) -> Optional[float]:
    """Coerce to float, rejecting None/empty/NaN/inf.

    Returning None on NaN is critical for the geo filter: ``NaN > radius``
    evaluates to False under IEEE 754, which would silently bypass
    radius-based discard if the caller forwarded the value to a comparison.
    """
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):  # rejects nan and ±inf
        return None
    return result


# ── Price parsing (unchanged from prior implementation) ──────────────────────

_PRICE_RE = re.compile(
    r"\d{1,3}(?:,\d{2,3})*,\d{3}(?:\.\d+)?"
    r"|\d+(?:\.\d+)?"
)


def _extract_price(entity: Dict[str, Any]) -> float:
    """Parse the first numeric value out of price-like fields.

    Handles thousands separators in Western and Indian numbering systems:
      "₹1,200"     -> 1200.0
      "$12,500.50" -> 12500.50
      "₹1,49,999"  -> 149999.0   (Indian lakh format)
      "12.5"       -> 12.5
      "no number"  -> 0.0
    """
    for key in ("price", "price_per_night", "price_range"):
        raw = entity.get(key)
        if raw:
            match = _PRICE_RE.search(str(raw))
            if match:
                try:
                    return float(match.group(0).replace(",", ""))
                except ValueError:
                    continue
    return 0.0
