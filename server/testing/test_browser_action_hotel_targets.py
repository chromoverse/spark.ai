"""Regression checks for hotel Book Now target selection.

No browser and no network: this only verifies that OSM/map URLs are not treated
as hotel booking targets.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from plugins.installed.web.tools.browser_action import (  # noqa: E402
    _booking_search_url,
    _hotel_booking_query,
    _hotel_direct_booking_url,
    _hotel_manual_booking_url,
)


def test_osm_hotel_uses_booking_search_not_map() -> None:
    entity = {
        "name": "Hotel Shanker",
        "type": "hotel",
        "location": "Kathmandu, Bagmati Province",
        "source_url": "https://www.openstreetmap.org/way/123",
        "maps_url": "https://www.google.com/maps/search/?api=1&query=Hotel+Shanker",
    }

    query = _hotel_booking_query(entity, entity["name"])
    url = _booking_search_url(query or "")

    assert _hotel_direct_booking_url(entity, None) is None
    assert _hotel_manual_booking_url(entity, None) is None
    assert "Hotel+Shanker" in url
    assert "Kathmandu" in url
    assert "openstreetmap" not in url
    assert "google.com/maps" not in url


def test_booking_url_is_preserved_for_booking_adapter() -> None:
    entity = {
        "name": "Hotel Shanker",
        "booking_url": "https://www.booking.com/hotel/np/hotel-shanker.html",
        "maps_url": "https://www.google.com/maps/search/?api=1&query=Hotel+Shanker",
    }

    assert _hotel_direct_booking_url(entity, None) == entity["booking_url"]
    assert _hotel_manual_booking_url(entity, None) == entity["booking_url"]


def test_official_site_is_manual_fallback_not_adapter_target() -> None:
    entity = {
        "name": "Hotel Shanker",
        "website": "https://www.shankerhotel.com.np/",
        "source_url": "https://www.openstreetmap.org/way/123",
    }

    assert _hotel_direct_booking_url(entity, None) is None
    assert _hotel_manual_booking_url(entity, None) == entity["website"]


def main() -> int:
    tests = (
        test_osm_hotel_uses_booking_search_not_map,
        test_booking_url_is_preserved_for_booking_adapter,
        test_official_site_is_manual_fallback_not_adapter_target,
    )
    for test in tests:
        test()
        print(f"{test.__name__} ... OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
