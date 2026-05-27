"""
Multi-provider chain — the single entry point web_research talks to.

Strategy
────────
Try providers in priority order (highest trust first):
  google_places  (if GOOGLE_PLACES_API_KEY set)
       ↓
  foursquare     (if FOURSQUARE_API_KEY set)
       ↓
  osm            (always available)

Each provider's ``supports(intent)`` decides whether it can even attempt
the request. ``search(...)`` is called on the first willing provider; if
it returns ≥ ``_MIN_ENTITIES_FOR_SHORTCIRCUIT`` results we're done. If
not, we walk down the chain.

We deliberately *don't* merge results across providers — merging needs
geo+name deduplication that's surprisingly hard to get right (two
slightly-misspelled hotels at adjacent coords should collapse; two real
neighbours shouldn't). Single-winner is simpler, lossless, and the
trust nudge in the ranker already biases higher-quality sources.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from . import (
    foursquare_provider,
    google_places_provider,
    osm_provider,
)
from .provider_registry import supported_intents

logger = logging.getLogger(__name__)

# Provider call order — earliest = highest priority. Keep aligned with
# PROVIDER_PRIORITY in __init__.py.
_CHAIN = [
    ("google_places", google_places_provider),
    ("foursquare",    foursquare_provider),
    ("osm",           osm_provider),
]

# If the first willing provider returns at least this many results, we
# don't fall through. Below this we try the next provider — protects
# against a provider that's technically "up" but returning sparse data
# for an unusual location.
_MIN_ENTITIES_FOR_SHORTCIRCUIT = 3


def supports(intent: str) -> bool:
    """True if any provider in the chain can handle this intent right now."""
    if intent not in supported_intents():
        return False
    return any(p.supports(intent) for _, p in _CHAIN)


async def search(
    intent: str,
    query: str,
    user_lat: float,
    user_lon: float,
    radius_km: float = 25.0,
    max_results: int = 25,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Run the chain. Returns ``(entities, sources)`` from the first
    provider that yielded enough results, or empty if nothing worked."""

    last_partial: Tuple[List[Dict[str, Any]], List[Dict[str, Any]]] = ([], [])

    for name, provider in _CHAIN:
        if not provider.supports(intent):
            logger.debug("multi_provider: %s skipped (not supported / no key)", name)
            continue
        try:
            entities, sources = await provider.search(
                intent=intent,
                query=query,
                user_lat=user_lat,
                user_lon=user_lon,
                radius_km=radius_km,
                max_results=max_results,
            )
        except Exception as exc:  # pragma: no cover — providers should never raise
            logger.warning("multi_provider: %s crashed: %s", name, exc)
            continue

        if len(entities) >= _MIN_ENTITIES_FOR_SHORTCIRCUIT:
            logger.info(
                "multi_provider: %s won with %d entities (chain short-circuit)",
                name, len(entities),
            )
            return entities, sources

        # Hang on to the best partial result so we don't return empty
        # when every provider returns 1–2 results.
        if len(entities) > len(last_partial[0]):
            last_partial = (entities, sources)
            logger.debug("multi_provider: %s yielded %d entities — trying next", name, len(entities))

    if last_partial[0]:
        logger.info(
            "multi_provider: chain exhausted; returning best partial (%d entities)",
            len(last_partial[0]),
        )
    return last_partial
