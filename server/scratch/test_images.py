import asyncio
import logging
import sys

sys.path.insert(0, '.')
logging.basicConfig(level=logging.DEBUG)

from plugins.installed.web.tools.entity_search import _enrich_images_nodriver

async def main():
    entities = [
        {
            "name": "Old House Cafe",
            "website": "https://www.facebook.com/OldHouseCafeNP/", # some URL
            "latitude": 27.71,
            "longitude": 85.32,
        },
        {
            "name": "Annapurna",
            "website": "", # empty to test search fallback
            "latitude": 27.71,
            "longitude": 85.32,
        }
    ]
    print("Running _enrich_images_nodriver...")
    await _enrich_images_nodriver(entities, top_n=2, user_city="Kathmandu")
    print("Entities after enrichment:")
    for e in entities:
        print(f"Name: {e.get('name')} | Website: {e.get('website')} | Images: {e.get('images')}")

if __name__ == "__main__":
    asyncio.run(main())
