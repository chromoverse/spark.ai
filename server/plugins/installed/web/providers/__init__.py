"""
Structured-retrieval providers for web_research.

These bypass DDGS+scrape+LLM-extract for intents where structured APIs exist.
The retrieval substrate guide (Retrival_GUIDE.md) is the design north star:
local entity intents (hotel, restaurant, local_service, place, event) should
resolve through Maps/Places-style providers, not SEO scraping.

Currently shipping
──────────────────
  - google_places_provider — Google Places Nearby Search (env-key: GOOGLE_PLACES_API_KEY)
  - foursquare_provider    — Foursquare Places v3 (env-key: FOURSQUARE_API_KEY)
  - osm_provider           — OpenStreetMap Overpass (always available, no key)
  - multi_provider         — chain that picks the first willing provider

Provider trust & priority
─────────────────────────
Each provider gets an intrinsic ``trust`` (how reliable its data is on
average) and a ``priority`` (chain order; lower = earlier). The ranker
multiplies per-entity ``confidence`` by source ``trust`` so low-quality
results get gently de-ranked when multiple providers eventually merge.

Activation
──────────
Google Places / Foursquare are scaffolded but dormant until their
respective env vars are populated. OSM is the always-on backstop.
"""

from typing import Dict

# Trust = baseline data quality of this source on average (0..1).
# Calibrate against ground truth as more providers come online.
PROVIDER_TRUST: Dict[str, float] = {
    "google_places": 0.95,
    "foursquare":    0.90,
    "geoapify":      0.85,
    "osm":           0.75,
    "browser_agent": 0.65,
    "scraped_html":  0.45,
    "ddgs_snippet":  0.35,
}

# Priority = retrieval order. Lower numbers run first.
PROVIDER_PRIORITY: Dict[str, int] = {
    "google_places": 1,
    "foursquare":    2,
    "geoapify":      3,
    "osm":           4,
    "browser_agent": 5,
    "scraped_html":  6,
    "ddgs_snippet":  7,
}


def provider_trust(source: str) -> float:
    return PROVIDER_TRUST.get(source, 0.5)


def provider_priority(source: str) -> int:
    return PROVIDER_PRIORITY.get(source, 99)


# Provider modules — imported after registries are defined so they can
# read from this package at module-load time.
from . import osm_provider              # noqa: E402
from . import google_places_provider    # noqa: E402
from . import foursquare_provider       # noqa: E402
from . import multi_provider            # noqa: E402
from . import geo_resolver              # noqa: E402

__all__ = [
    "osm_provider",
    "google_places_provider",
    "foursquare_provider",
    "multi_provider",
    "geo_resolver",
    "PROVIDER_TRUST",
    "PROVIDER_PRIORITY",
    "provider_trust",
    "provider_priority",
]
