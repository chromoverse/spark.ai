"""Quick smoke test: does the DDG image search + _is_valid_image pipeline
return usable image URLs for a Kathmandu café?"""
import asyncio, sys, os
sys.path.insert(0, ".")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import logging
logging.basicConfig(level=logging.WARNING)

from plugins.installed.web.tools.entity_search import _fetch_ddg_images, _is_valid_image

async def main():
    queries = [
        "Old House Cafe Kathmandu",
        "Annapurna Cafe Kathmandu",
        "Ice Cafe Kathmandu",
    ]
    for q in queries:
        imgs = await _fetch_ddg_images(q, limit=3)
        status = "OK" if imgs else "EMPTY"
        # print name ascii-safe
        print(f"[{status}] {q}: {len(imgs)} images")
        for i, url in enumerate(imgs):
            print(f"  {i+1}. {url[:100]}...")

asyncio.run(main())
