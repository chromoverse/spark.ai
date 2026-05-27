"""
Cross-provider filter registry for nearby-entity intents.

One source of truth for what each ``intent`` (and, within ``local_service``,
each amenity) means across **every** structured provider we support
(OSM Overpass today; Google Places + Foursquare scaffolded).

Layout
──────
  INTENT_MAP    — static intents (hotel/restaurant/place/event) → per-provider
                  filters.
  AMENITIES     — canonical local-service amenities → per-provider filters,
                  with lemmas for the lexical fast path and a natural-language
                  description for the semantic fallback.
  overpass_filters / google_type / foursquare_query
                — provider-facing accessors.

Why one table
─────────────
"hospital" must mean the same thing to OSM, Google Places, and Foursquare;
keeping that mapping in three places is how providers drift apart silently.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Per-provider filter container ────────────────────────────────────────────

@dataclass(frozen=True)
class ProviderFilter:
    """The provider-specific selector for a single canonical concept."""
    osm_filters: List[str] = field(default_factory=list)
    google_type: Optional[str] = None       # Google Places legacy `type` value
    google_keyword: Optional[str] = None    # Optional `keyword` for free-text refinement
    foursquare_query: Optional[str] = None  # Foursquare v3 `query` value
    foursquare_categories: List[str] = field(default_factory=list)  # numeric category IDs


# ── Static intent → provider filters ─────────────────────────────────────────
# These intents map 1:1 to a single concept. ``local_service`` is the
# exception — handled separately via AMENITIES below.

INTENT_MAP: Dict[str, ProviderFilter] = {
    "hotel_search": ProviderFilter(
        osm_filters=[
            'node["tourism"~"^(hotel|hostel|guest_house|motel|apartment|chalet)$"]',
            'way["tourism"~"^(hotel|hostel|guest_house|motel|apartment|chalet)$"]',
        ],
        google_type="lodging",
        foursquare_query="hotel",
        foursquare_categories=["19014"],  # Hotel
    ),
    "restaurant_search": ProviderFilter(
        osm_filters=[
            'node["amenity"~"^(restaurant|cafe|fast_food|food_court|bar|pub)$"]',
            'way["amenity"~"^(restaurant|cafe|fast_food|food_court|bar|pub)$"]',
        ],
        google_type="restaurant",
        foursquare_query="restaurant",
        foursquare_categories=["13065"],  # Restaurant
    ),
    "place_search": ProviderFilter(
        osm_filters=[
            'node["tourism"~"^(attraction|museum|viewpoint|gallery|theme_park|zoo|aquarium)$"]',
            'way["tourism"~"^(attraction|museum|viewpoint|gallery|theme_park|zoo|aquarium)$"]',
            'node["historic"]',
            'way["historic"]',
            'node["leisure"~"^(park|garden|nature_reserve)$"]',
            'way["leisure"~"^(park|garden|nature_reserve)$"]',
        ],
        google_type="tourist_attraction",
        foursquare_query="attraction",
        foursquare_categories=["16000"],  # Landmarks and Outdoors
    ),
    "event_search": ProviderFilter(
        osm_filters=[
            'node["amenity"~"^(theatre|cinema|nightclub|events_venue|community_centre|conference_centre)$"]',
            'way["amenity"~"^(theatre|cinema|nightclub|events_venue|community_centre|conference_centre)$"]',
        ],
        google_type="movie_theater",  # closest single type; Places has no "event" type
        google_keyword="event",
        foursquare_query="theater",
        foursquare_categories=["10032"],  # Theater
    ),
    "college_search": ProviderFilter(
        osm_filters=[
            'node["amenity"~"^(school|college|university)$"]',
            'way["amenity"~"^(school|college|university)$"]',
        ],
        google_type="university",
        foursquare_query="university",
        foursquare_categories=["12013"],  # University
    ),
}


# ── local_service: canonical amenities ───────────────────────────────────────

@dataclass(frozen=True)
class Amenity:
    """One canonical local-service concept (hospital, gym, …) with
    cross-provider filters and lexical/semantic match hints."""
    name: str
    lemmas: List[str]
    description: str
    filters: ProviderFilter


AMENITIES: List[Amenity] = [
    Amenity("hospital",
        lemmas=["hospital", "hospitals", "emergency", "er", "trauma"],
        description="a hospital or emergency room providing urgent medical care",
        filters=ProviderFilter(
            osm_filters=['node["amenity"="hospital"]', 'way["amenity"="hospital"]'],
            google_type="hospital",
            foursquare_query="hospital",
        ),
    ),
    Amenity("clinic",
        lemmas=["clinic", "clinics", "doctor", "doctors", "physician", "physicians", "gp"],
        description="a medical clinic or general practitioner's office for non-emergency care",
        filters=ProviderFilter(
            osm_filters=['node["amenity"~"^(clinic|doctors)$"]', 'way["amenity"~"^(clinic|doctors)$"]'],
            google_type="doctor",
            foursquare_query="clinic",
        ),
    ),
    Amenity("pharmacy",
        lemmas=["pharmacy", "pharmacies", "chemist", "chemists", "drugstore", "drugstores", "medical"],
        description="a pharmacy or drugstore where medication can be purchased",
        filters=ProviderFilter(
            osm_filters=['node["amenity"="pharmacy"]', 'way["amenity"="pharmacy"]'],
            google_type="pharmacy",
            foursquare_query="pharmacy",
        ),
    ),
    Amenity("dentist",
        lemmas=["dentist", "dentists", "dental"],
        description="a dentist or dental clinic for tooth care",
        filters=ProviderFilter(
            osm_filters=['node["amenity"="dentist"]', 'way["amenity"="dentist"]'],
            google_type="dentist",
            foursquare_query="dentist",
        ),
    ),
    Amenity("veterinary",
        lemmas=["vet", "vets", "veterinary", "veterinarian", "veterinarians", "animal"],
        description="a veterinarian or animal clinic for pet care",
        filters=ProviderFilter(
            osm_filters=['node["amenity"="veterinary"]', 'way["amenity"="veterinary"]'],
            google_type="veterinary_care",
            foursquare_query="veterinarian",
        ),
    ),
    Amenity("gym",
        lemmas=["gym", "gyms", "fitness", "workout", "crossfit", "yoga", "pilates"],
        description="a gym, fitness centre, or place to work out and exercise",
        filters=ProviderFilter(
            osm_filters=[
                'node["leisure"~"^(fitness_centre|sports_centre)$"]',
                'way["leisure"~"^(fitness_centre|sports_centre)$"]',
            ],
            google_type="gym",
            foursquare_query="gym",
        ),
    ),
    Amenity("bank",
        lemmas=["bank", "banks", "atm", "atms", "cashpoint", "cashpoints"],
        description="a bank branch or ATM machine for cash withdrawal and banking",
        filters=ProviderFilter(
            osm_filters=['node["amenity"~"^(bank|atm)$"]', 'way["amenity"="bank"]'],
            google_type="bank",
            foursquare_query="bank",
        ),
    ),
    Amenity("fuel",
        lemmas=["gas", "petrol", "fuel", "charging", "ev"],
        description="a gas station, petrol pump, or EV charging point",
        filters=ProviderFilter(
            osm_filters=[
                'node["amenity"~"^(fuel|charging_station)$"]',
                'way["amenity"~"^(fuel|charging_station)$"]',
            ],
            google_type="gas_station",
            foursquare_query="gas station",
        ),
    ),
    Amenity("school",
        lemmas=["school", "schools", "college", "colleges", "university", "universities"],
        description="a school, college, or university for education",
        filters=ProviderFilter(
            osm_filters=[
                'node["amenity"~"^(school|college|university)$"]',
                'way["amenity"~"^(school|college|university)$"]',
            ],
            google_type="school",
            foursquare_query="school",
        ),
    ),
    Amenity("post_office",
        lemmas=["post", "postoffice", "courier", "couriers", "mail"],
        description="a post office or courier service for sending mail and packages",
        filters=ProviderFilter(
            osm_filters=['node["amenity"="post_office"]', 'way["amenity"="post_office"]'],
            google_type="post_office",
            foursquare_query="post office",
        ),
    ),
    Amenity("police",
        lemmas=["police", "cops", "law"],
        description="a police station for reporting crimes and law enforcement",
        filters=ProviderFilter(
            osm_filters=['node["amenity"="police"]', 'way["amenity"="police"]'],
            google_type="police",
            foursquare_query="police station",
        ),
    ),
    Amenity("library",
        lemmas=["library", "libraries"],
        description="a public library for borrowing books and reading",
        filters=ProviderFilter(
            osm_filters=['node["amenity"="library"]', 'way["amenity"="library"]'],
            google_type="library",
            foursquare_query="library",
        ),
    ),
    Amenity("salon",
        lemmas=["salon", "salons", "barber", "barbers", "hairdresser", "hairdressers", "spa", "spas"],
        description="a hair salon, barber, beauty parlour, or spa for personal grooming",
        filters=ProviderFilter(
            osm_filters=[
                'node["shop"~"^(hairdresser|beauty)$"]',
                'way["shop"~"^(hairdresser|beauty)$"]',
                'node["amenity"="spa"]',
            ],
            google_type="beauty_salon",
            foursquare_query="salon",
        ),
    ),
    Amenity("supermarket",
        lemmas=["supermarket", "supermarkets", "grocery", "groceries", "grocer", "grocers", "market"],
        description="a supermarket or grocery store for everyday food and household shopping",
        filters=ProviderFilter(
            osm_filters=[
                'node["shop"~"^(supermarket|convenience|grocery)$"]',
                'way["shop"~"^(supermarket|convenience|grocery)$"]',
            ],
            google_type="supermarket",
            foursquare_query="supermarket",
        ),
    ),
    Amenity("parking",
        lemmas=["parking", "carpark", "park"],
        description="a parking lot or car park for leaving a vehicle",
        filters=ProviderFilter(
            osm_filters=['node["amenity"="parking"]', 'way["amenity"="parking"]'],
            google_type="parking",
            foursquare_query="parking",
        ),
    ),
    Amenity("cafe",
        lemmas=["cafe", "cafes", "caffee", "coffee", "coffeeshop", "coffeehouse",
                "espresso", "latte", "cappuccino", "tea", "teahouse"],
        description="a cafe, coffee shop, or tea house serving beverages and light meals",
        filters=ProviderFilter(
            osm_filters=[
                'node["amenity"="cafe"]',
                'way["amenity"="cafe"]',
            ],
            google_type="cafe",
            foursquare_query="cafe",
            foursquare_categories=["13032"],  # Coffee Shop
        ),
    ),
    Amenity("restaurant",
        lemmas=["restaurant", "restaurants", "diner", "diners", "eatery", "eateries",
                "bistro", "bistros", "dining", "food"],
        description="a restaurant, diner, or eatery serving full meals",
        filters=ProviderFilter(
            osm_filters=[
                'node["amenity"="restaurant"]',
                'way["amenity"="restaurant"]',
            ],
            google_type="restaurant",
            foursquare_query="restaurant",
            foursquare_categories=["13065"],  # Restaurant
        ),
    ),
]


# ── Lexical + semantic resolution for local_service ──────────────────────────

_SEMANTIC_THRESHOLD = 0.55
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(query: str) -> List[str]:
    return _TOKEN_RE.findall(query.lower())


def _lemma_match(query: str) -> Optional[Amenity]:
    tokens = set(_tokenize(query))
    if not tokens:
        return None
    for amenity in AMENITIES:
        if tokens.intersection(amenity.lemmas):
            return amenity
    return None


async def _semantic_match(query: str) -> Optional[Amenity]:
    """Cosine-similarity the query against amenity descriptions via BGE-M3."""
    try:
        from app.ml import get_embeddings
        import numpy as np

        docs = [a.description for a in AMENITIES]
        embeddings = await get_embeddings([query] + docs)
        if not embeddings or len(embeddings) != len(docs) + 1:
            return None
        arr = np.array(embeddings, dtype=np.float32)
        q = arr[0]
        qn = np.linalg.norm(q) or 1.0
        d = arr[1:]
        dn = np.linalg.norm(d, axis=1)
        dn = np.where(dn == 0, 1.0, dn)
        cosines = (d @ q) / (dn * qn)
        best_idx = int(np.argmax(cosines))
        best_score = float(cosines[best_idx])
        if best_score >= _SEMANTIC_THRESHOLD:
            return AMENITIES[best_idx]
        logger.debug(
            "provider_registry: semantic best %s @ %.3f below threshold for %r",
            AMENITIES[best_idx].name, best_score, query,
        )
        return None
    except Exception as exc:
        logger.info("provider_registry: semantic classifier unavailable: %s", exc)
        return None


async def resolve_filter(intent: str, query: str) -> Optional[ProviderFilter]:
    """Return the cross-provider ProviderFilter for an intent + query.

    For static intents this is a dict lookup. For ``local_service`` we
    run the lexical lemma match, then fall back to the semantic classifier,
    returning the matched amenity's filter. None → caller should fall back
    to web search.
    """
    if intent != "local_service":
        return INTENT_MAP.get(intent)
    amenity = _lemma_match(query)
    if amenity is None:
        amenity = await _semantic_match(query)
    return amenity.filters if amenity else None


# ── Provider-facing accessors ────────────────────────────────────────────────

async def overpass_filters(intent: str, query: str) -> Optional[List[str]]:
    """OSM-specific accessor: returns just the Overpass body filters."""
    f = await resolve_filter(intent, query)
    return f.osm_filters if f and f.osm_filters else None


async def google_filter(intent: str, query: str) -> Optional[ProviderFilter]:
    """Google Places: returns the whole ProviderFilter so caller can read
    both ``google_type`` and ``google_keyword``. None when nothing maps."""
    f = await resolve_filter(intent, query)
    if not f or not f.google_type:
        return None
    return f


async def foursquare_filter(intent: str, query: str) -> Optional[ProviderFilter]:
    """Foursquare: returns the ProviderFilter; caller picks
    ``foursquare_query`` and/or ``foursquare_categories``."""
    f = await resolve_filter(intent, query)
    if not f or not (f.foursquare_query or f.foursquare_categories):
        return None
    return f


def supported_intents() -> List[str]:
    """Intents for which any structured filter mapping exists."""
    return list(INTENT_MAP.keys()) + ["local_service"]
