"""
Normalized result schema for structured providers.

All providers (OSM, future Google Places / Foursquare / Geoapify) return
``ProviderEntity`` dicts. The web_research tool re-shapes these into the
per-schema entity dict (HotelEntity, RestaurantEntity, …) before ranking.

Keeping a *single* provider-side schema means new backends drop in without
touching the entity-pydantic models or the ranker.
"""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


class ProviderEntity(BaseModel):
    """Backend-agnostic representation of a single retrieved entity."""

    # Identity
    name: str
    source: str                          # "osm" | "google_places" | "foursquare" | …
    source_id: Optional[str] = None      # backend-native id (e.g. OSM "node/12345")
    source_url: Optional[str] = None     # canonical page for the entity on its source

    # Geography (the whole point — these are non-optional in practice for nearby intents)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None

    # Classification
    category: Optional[str] = None       # human-readable category (e.g. "Hotel", "Restaurant")
    tags: List[str] = Field(default_factory=list)

    # Quality signals
    rating: Optional[float] = None
    review_count: Optional[int] = None
    price_level: Optional[int] = None    # 1..4 if known
    price_text: Optional[str] = None     # raw price string if present

    # Contact / web
    website: Optional[str] = None
    phone: Optional[str] = None
    hours: Optional[str] = None

    # Per-entity confidence (0..1) — *this specific result's* completeness
    # (has coords? has rating? has hours?). Default 0.5 = "no strong opinion".
    confidence: float = 0.5

    def effective_trust(self) -> float:
        """source trust × per-entity confidence, clamped to [0, 1].

        This is the value the ranker consumes. A perfect Google Places hit
        (trust=0.95, confidence=1.0) gives 0.95; a low-confidence scraped
        entity (trust=0.45, confidence=0.4) gives 0.18.
        """
        # Local import avoids the package-init circular at module-load time.
        from . import provider_trust
        return max(0.0, min(1.0, provider_trust(self.source) * self.confidence))
