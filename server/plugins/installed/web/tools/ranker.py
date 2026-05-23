"""
Multi-factor entity ranker. Pure math — no LLM calls.

Scoring weights per entity type (all sum to 1.0):
  hotel:          rating 0.4 | price 0.3 | review_count 0.2 | relevance 0.1
  product:        price 0.4  | rating 0.3 | review_count 0.2 | relevance 0.1
  restaurant:     rating 0.45| price 0.2  | review_count 0.2 | relevance 0.15
  local_business: rating 0.5 | review_count 0.3 | relevance 0.2
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

_WEIGHTS: Dict[str, Dict[str, float]] = {
    "hotel": {
        "rating": 0.4,
        "price": 0.3,
        "review_count": 0.2,
        "relevance": 0.1,
    },
    "product": {
        "price": 0.4,
        "rating": 0.3,
        "review_count": 0.2,
        "relevance": 0.1,
    },
    "restaurant": {
        "rating": 0.45,
        "price": 0.20,
        "review_count": 0.20,
        "relevance": 0.15,
    },
    "local_business": {
        "rating": 0.50,
        "review_count": 0.30,
        "relevance": 0.20,
    },
}

_DEFAULT_WEIGHTS = {"rating": 0.5, "review_count": 0.3, "relevance": 0.2}


def rank_entities(
    entities: List[Dict[str, Any]],
    entity_schema: str,
    query: str,
) -> List[Dict[str, Any]]:
    """
    Score and sort entities descending. Returns new list with _score injected.
    """
    if not entities:
        return []

    weights = _WEIGHTS.get(entity_schema, _DEFAULT_WEIGHTS)
    query_words = set(re.findall(r"\w+", query.lower()))

    # Compute per-factor ranges for normalisation
    ratings = [float(e.get("rating") or 0) for e in entities]
    reviews = [int(e.get("review_count") or 0) for e in entities]
    prices  = [_extract_price(e) for e in entities]

    max_rating = max(ratings) if any(r > 0 for r in ratings) else 5.0
    max_reviews = max(reviews) if any(r > 0 for r in reviews) else 1
    # For price: lower is better — invert normalisation
    valid_prices = [p for p in prices if p > 0]
    min_price = min(valid_prices) if valid_prices else 0
    max_price = max(valid_prices) if valid_prices else 1

    scored: List[Dict[str, Any]] = []
    for entity, rating, review, price in zip(entities, ratings, reviews, prices):
        score = 0.0

        if "rating" in weights and max_rating > 0:
            score += weights["rating"] * (rating / max_rating)

        if "review_count" in weights and max_reviews > 0:
            score += weights["review_count"] * (review / max_reviews)

        if "price" in weights:
            if price > 0 and max_price > min_price:
                # Cheaper = higher price score
                norm = 1.0 - (price - min_price) / (max_price - min_price)
                score += weights["price"] * norm
            elif price == 0:
                # No price info — neutral contribution
                score += weights["price"] * 0.5

        if "relevance" in weights:
            name_words = set(re.findall(r"\w+", str(entity.get("name", "")).lower()))
            desc_words = set(re.findall(r"\w+", str(entity.get("description", "")).lower()))
            hits = len(query_words & (name_words | desc_words))
            rel = hits / len(query_words) if query_words else 0.0
            score += weights["relevance"] * rel

        entity["_score"] = round(score, 4)
        scored.append(entity)

    scored.sort(key=lambda e: e["_score"], reverse=True)
    return scored


def _extract_price(entity: Dict[str, Any]) -> float:
    """Parse the first numeric value out of price/price_per_night strings.

    Handles thousands separators in both Western and Indian numbering systems:
      "₹1,200"        -> 1200.0
      "$12,500.50"    -> 12500.50
      "$1,234,567"    -> 1234567.0
      "₹1,49,999"     -> 149999.0   (Indian lakh format)
      "12.5"          -> 12.5
      "no number"     -> 0.0
    """
    # First alt: digits with comma groups (2- or 3-digit), where the last
    # group must be 3 digits (rejects half-baked tokens like "5,67").
    # Second alt: plain digits / decimals with no commas.
    _PRICE_RE = re.compile(
        r"\d{1,3}(?:,\d{2,3})*,\d{3}(?:\.\d+)?"
        r"|\d+(?:\.\d+)?"
    )
    for key in ("price", "price_per_night", "price_range"):
        raw = entity.get(key)
        if raw:
            match = _PRICE_RE.search(str(raw))
            if match:
                return float(match.group(0).replace(",", ""))
    return 0.0
