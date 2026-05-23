"""
Manual test: web_research for "cheapest hotels near me"

Pipeline tested here mirrors the SQH chain:
  Step 1: current_location  - resolve IP -> city/region
  Step 2: web_research      - hotel_search with city injected via location param

Run from the server/ directory:
  python tests/manual/test_web_research_hotels.py
"""

import asyncio
import json
import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))


def _hr(label: str = "") -> None:
    print(f"\n{'-' * 60}")
    if label:
        print(f"  {label}")
        print(f"{'-' * 60}")


def _print_entity(i: int, e: dict) -> None:
    score = e.get("_score", "n/a")
    print(f"\n  [{i}] {e.get('name', '(unnamed)')}")
    if e.get("price_per_night"):
        print(f"       Price  : {e['price_per_night']}")
    if e.get("rating"):
        rc = f"  ({e['review_count']} reviews)" if e.get("review_count") else ""
        print(f"       Rating : {e['rating']}/5{rc}")
    if e.get("location"):
        print(f"       Where  : {e['location']}")
    if e.get("amenities"):
        print(f"       Amenities: {', '.join(e['amenities'][:5])}")
    if e.get("booking_url"):
        print(f"       Book   : {e['booking_url']}")
    if e.get("description"):
        desc = e["description"][:120]
        print(f"       Info   : {desc}")
    images = e.get("images", [])
    if images:
        print(f"       Images : {len(images)} found")
        for url in images:
            print(f"                {url}")
    else:
        print(f"       Images : (none)")
    print(f"       Score  : {score}")


async def get_location() -> dict:
    from plugins.installed.system.tools.location import CurrentLocationTool
    tool = CurrentLocationTool()
    result = await tool._execute({"detailed": False})
    if not result.success:
        raise RuntimeError(f"current_location failed: {result.error}")
    return result.data


async def run_web_research(city: str, region: str) -> object:
    from plugins.installed.web.tools.research import WebResearchTool
    location_str = f"{city}, {region}" if region and region != "N/A" else city
    tool = WebResearchTool()
    return await tool._execute({
        "query": "cheapest hotels near me",
        "formatted_queries": [
            f"site:budgetyourtrip.com cheap hotels {location_str}",
            f"site:hostelworld.com {location_str} budget hotel",
            f"cheap hotels {location_str} price per night",
        ],
        "intent": "hotel_search",
        "entity_schema": "hotel",
        "response_format": "entity_cards",
        "location": location_str,
        "max_results": 6,
        "max_chars": 8000,
    })


async def main() -> None:
    print("\n=== web_research: cheapest hotels near me ===")

    _hr("STEP 1 - current_location")
    print("  Resolving IP geolocation...")
    try:
        loc = await get_location()
    except RuntimeError as e:
        print(f"  FAILED: {e}")
        print("  Falling back to hardcoded location for testing.")
        loc = {"city": "New York", "region": "New York", "country": "United States", "country_code": "US"}

    city    = loc.get("city", "Unknown")
    region  = loc.get("region", "")
    country = loc.get("country", "")
    print(f"  OK  City    : {city}")
    print(f"      Region  : {region}")
    print(f"      Country : {country}")
    print(f"      Lat/Lon : {loc.get('latitude')}, {loc.get('longitude')}")

    location_str = f"{city}, {region}" if region and region != "N/A" else city

    _hr(f"STEP 2 - web_research  [location={location_str!r}]")
    print("  Running: search -> scrape -> entity extract -> rank...")

    result = await run_web_research(city, region)

    if not result.success:
        print(f"  FAILED: {result.error}")
        return

    data        = result.data
    intent      = data.get("intent", "?")
    result_type = data.get("result_type", "?")
    entities    = data.get("entities", [])
    sources     = data.get("sources", [])

    _hr(f"RESULTS  [{intent} / {result_type}]  -  {len(entities)} entities found")

    if not entities:
        print("  No hotel entities extracted.")
        print("  Raw answer :", data.get("answer"))
        print("  Summary    :", data.get("summary"))
    else:
        for i, e in enumerate(entities, 1):
            _print_entity(i, e)

    _hr("SOURCES")
    for s in sources[:5]:
        title = s.get("title", "(no title)")[:60]
        url   = s.get("url", "")
        print(f"  - {title}")
        print(f"    {url}")

    _hr("RAW JSON (first entity)")
    if entities:
        print(json.dumps(entities[0], indent=4, default=str))

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
