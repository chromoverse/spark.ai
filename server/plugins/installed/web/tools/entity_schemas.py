"""
Entity data contracts for web_research structured extraction.

Each model maps to one entity_schema value SQH can pass to web_research:
  hotel | product | restaurant | local_business
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
    amenities: List[str] = Field(default_factory=list)
    images: List[str] = Field(default_factory=list)
    booking_url: Optional[str] = None
    maps_url: Optional[str] = None
    description: Optional[str] = None
    stars: Optional[int] = None
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
    phone: Optional[str] = None
    hours: Optional[str] = None
    menu_url: Optional[str] = None
    booking_url: Optional[str] = None
    maps_url: Optional[str] = None
    images: List[str] = Field(default_factory=list)
    features: List[str] = Field(default_factory=list)
    source_url: Optional[str] = None


class LocalBusinessEntity(BaseModel):
    type: str = "local_business"
    name: str
    category: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    hours: Optional[str] = None
    website: Optional[str] = None
    maps_url: Optional[str] = None
    description: Optional[str] = None
    images: List[str] = Field(default_factory=list)
    source_url: Optional[str] = None


ENTITY_SCHEMA_MAP = {
    "hotel": HotelEntity,
    "product": ProductEntity,
    "restaurant": RestaurantEntity,
    "local_business": LocalBusinessEntity,
}

ENTITY_FIELD_DESCRIPTIONS = {
    "hotel": (
        "Extract: name, price_per_night (e.g. '$120/night'), rating (0-5 float), "
        "review_count, location, amenities (list), booking_url, stars (1-5 int), description."
    ),
    "product": (
        "Extract: name, price (current price string), original_price (if discounted), "
        "rating (0-5 float), review_count, brand, availability, buy_url, description, features (list)."
    ),
    "restaurant": (
        "Extract: name, cuisine, price_range (e.g. '$$'), rating (0-5 float), "
        "review_count, address, phone, hours, menu_url, booking_url, features (list)."
    ),
    "local_business": (
        "Extract: name, category, rating (0-5 float), review_count, address, "
        "phone, hours, website, description."
    ),
}
