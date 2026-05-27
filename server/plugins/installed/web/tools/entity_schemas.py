"""
Entity data contracts for web_research structured extraction.

Each model maps to one entity_schema value SQH can pass to web_research:
  hotel | product | restaurant | local_business |
  person | movie | event | college | place | flight

Coords ownership
────────────────
``latitude`` / ``longitude`` are owned by *structured providers* (OSM today,
Google Places / Foursquare next). The LLM-extraction path is the fallback
when no provider covers the intent and is allowed to *opportunistically*
fill coords only when they are literally visible on the page (e.g. an
embedded map JSON or microdata). It must never guess them — geo-filtering
depends on the integrity of these values.
"""

from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field


class HotelEntity(BaseModel):
    type: str = "hotel"
    name: str
    price_per_night: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    location: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    amenities: List[str] = Field(default_factory=list)
    images: List[str] = Field(default_factory=list)
    booking_url: Optional[str] = None
    maps_url: Optional[str] = None
    description: Optional[str] = None
    stars: Optional[int] = None
    source: Optional[str] = None
    source_url: Optional[str] = None


class ProductEntity(BaseModel):
    type: str = "product"
    name: str
    price: Optional[str] = None
    original_price: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    brand: Optional[str] = None
    availability: Optional[str] = None
    images: List[str] = Field(default_factory=list)
    buy_url: Optional[str] = None
    description: Optional[str] = None
    features: List[str] = Field(default_factory=list)
    source_url: Optional[str] = None


class RestaurantEntity(BaseModel):
    type: str = "restaurant"
    name: str
    cuisine: Optional[str] = None
    price_range: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    phone: Optional[str] = None
    hours: Optional[str] = None
    menu_url: Optional[str] = None
    booking_url: Optional[str] = None
    maps_url: Optional[str] = None
    images: List[str] = Field(default_factory=list)
    features: List[str] = Field(default_factory=list)
    source: Optional[str] = None
    source_url: Optional[str] = None


class LocalBusinessEntity(BaseModel):
    type: str = "local_business"
    name: str
    category: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    phone: Optional[str] = None
    hours: Optional[str] = None
    website: Optional[str] = None
    maps_url: Optional[str] = None
    description: Optional[str] = None
    images: List[str] = Field(default_factory=list)
    source: Optional[str] = None
    source_url: Optional[str] = None


class PersonEntity(BaseModel):
    type: str = "person"
    name: str
    title: Optional[str] = None
    born: Optional[str] = None
    nationality: Optional[str] = None
    known_for: Optional[str] = None
    bio: Optional[str] = None
    images: List[str] = Field(default_factory=list)
    website: Optional[str] = None
    social_links: List[str] = Field(default_factory=list)
    source_url: Optional[str] = None


class MovieShowEntity(BaseModel):
    type: str = "movie"
    name: str
    year: Optional[str] = None
    genre: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    director: Optional[str] = None
    cast: List[str] = Field(default_factory=list)
    runtime: Optional[str] = None
    plot: Optional[str] = None
    streaming_on: List[str] = Field(default_factory=list)
    images: List[str] = Field(default_factory=list)
    trailer_url: Optional[str] = None
    source_url: Optional[str] = None


class EventEntity(BaseModel):
    type: str = "event"
    name: str
    date: Optional[str] = None
    time: Optional[str] = None
    venue: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    price: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    images: List[str] = Field(default_factory=list)
    booking_url: Optional[str] = None
    maps_url: Optional[str] = None
    source: Optional[str] = None
    source_url: Optional[str] = None


class CollegeEntity(BaseModel):
    type: str = "college"
    name: str
    location: Optional[str] = None
    ranking: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    type_label: Optional[str] = None
    programs: List[str] = Field(default_factory=list)
    tuition: Optional[str] = None
    acceptance_rate: Optional[str] = None
    description: Optional[str] = None
    images: List[str] = Field(default_factory=list)
    website: Optional[str] = None
    maps_url: Optional[str] = None
    source_url: Optional[str] = None


class PlaceEntity(BaseModel):
    type: str = "place"
    name: str
    location: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    category: Optional[str] = None
    hours: Optional[str] = None
    price: Optional[str] = None
    description: Optional[str] = None
    images: List[str] = Field(default_factory=list)
    maps_url: Optional[str] = None
    website: Optional[str] = None
    source: Optional[str] = None
    source_url: Optional[str] = None


class FlightEntity(BaseModel):
    type: str = "flight"
    name: str
    airline: Optional[str] = None
    departure: Optional[str] = None
    arrival: Optional[str] = None
    duration: Optional[str] = None
    price: Optional[str] = None
    stops: Optional[str] = None
    aircraft: Optional[str] = None
    images: List[str] = Field(default_factory=list)
    booking_url: Optional[str] = None
    source_url: Optional[str] = None


ENTITY_SCHEMA_MAP = {
    "hotel": HotelEntity,
    "product": ProductEntity,
    "restaurant": RestaurantEntity,
    "local_business": LocalBusinessEntity,
    "person": PersonEntity,
    "movie": MovieShowEntity,
    "event": EventEntity,
    "college": CollegeEntity,
    "place": PlaceEntity,
    "flight": FlightEntity,
}

ENTITY_FIELD_DESCRIPTIONS = {
    "hotel": (
        "Extract: name, price_per_night (e.g. '$120/night'), rating (0-5 float), "
        "review_count, location, address (street/full address), amenities (list), "
        "booking_url, stars (1-5 int), description. "
        "Only include latitude/longitude (decimal degrees) when they are LITERALLY visible "
        "on the page (embedded map JSON, microdata 'geo.latitude', explicit 'lat=…' params). "
        "Never guess coords — the structured providers own them and a hallucinated value "
        "breaks geo-filtering."
    ),
    "product": (
        "Extract: name, price (current price string), original_price (if discounted), "
        "rating (0-5 float), review_count, brand, availability, buy_url, description, features (list)."
    ),
    "restaurant": (
        "Extract: name, cuisine, price_range (e.g. '$$'), rating (0-5 float), "
        "review_count, address, phone, hours, menu_url, booking_url, features (list). "
        "Only include latitude/longitude when literally visible on the page — never guess."
    ),
    "local_business": (
        "Extract: name, category, rating (0-5 float), review_count, address, "
        "phone, hours, website, description. "
        "Only include latitude/longitude when literally visible on the page — never guess."
    ),
    "person": (
        "Extract: name, title (role/occupation e.g. 'Actor', 'CEO'), born (date or year), "
        "nationality, known_for (brief phrase), bio (1-2 sentences), website, social_links (list of URLs)."
    ),
    "movie": (
        "Extract: name (film/show title), year, genre, rating (0-10 float from IMDb/RT), "
        "review_count, director, cast (list of actor names), runtime (e.g. '2h 15m'), "
        "plot (1-2 sentences), streaming_on (list e.g. ['Netflix','Prime']), trailer_url."
    ),
    "event": (
        "Extract: name, date (e.g. 'June 15, 2026'), time, venue (venue name), "
        "address, price (ticket price string), description, "
        "category (concert/conference/festival/sports/etc), booking_url. "
        "Only include latitude/longitude when literally visible on the page — never guess."
    ),
    "college": (
        "Extract: name, location (city/state/country), ranking (e.g. '#5 in India'), "
        "rating (0-5 float), type_label (Private/Public/IIT/NIT/etc), "
        "programs (list of offered degrees/fields), tuition (fee string), "
        "acceptance_rate (e.g. '12%'), description, website."
    ),
    "place": (
        "Extract: name, location (city/country), address, rating (0-5 float), review_count, "
        "category (temple/park/museum/beach/fort/etc), hours (opening hours), "
        "price (entry fee if any), description (1-2 sentences), website. "
        "Only include latitude/longitude when literally visible on the page — never guess."
    ),
    "flight": (
        "Extract: name (airline + flight number or route e.g. 'Air India AI-814'), "
        "airline, departure (airport code + time e.g. 'DEL 06:30 AM'), "
        "arrival (airport code + time), duration (e.g. '2h 15m'), "
        "price (fare string), stops (e.g. 'Non-stop' or '1 stop via HYD'), "
        "aircraft (e.g. 'Boeing 737'), booking_url."
    ),
}
