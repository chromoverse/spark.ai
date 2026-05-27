import asyncio
import logging
import sys
from typing import List, Dict

sys.path.insert(0, '.')
logging.basicConfig(level=logging.WARNING)

from plugins.installed.web.tools.scrape import WebScrapeTool
from plugins.installed.web.tools.search import WebSearchTool

def _is_valid_image(url: str) -> bool:
    low = url.lower()
    skip_terms = (
        "1x1", "pixel", "spacer", "blank", "logo", "icon", "sprite", "data:",
        "tiny.png", "placeholder", "openstreetmap.org", "osm.org", "matomo",
        "google.com", "gstatic.com", "facebook.com/tr", "analytics", "doubleclick",
        "favicon", "wp-content/themes", "wp-content/uploads/assets", "theme"
    )
    if any(term in low for term in skip_terms):
        return False
    if low.endswith((".svg", ".ico", ".gif")) and "photo" not in low:
        return False
    return True

async def _fetch_ddg_images(query: str, limit: int = 3) -> List[str]:
    try:
        from ddgs import DDGS
        def _sync_search():
            with DDGS(timeout=8) as ddgs:
                return list(ddgs.images(query, max_results=limit, safesearch="moderate"))
        
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(None, _sync_search)
        return [r["image"] for r in results if r.get("image") and _is_valid_image(r["image"])]
    except Exception as exc:
        print("DDG image search failed for:", query, exc)
        return []

async def _fetch_one(entity: Dict, user_city: str, scrape_tool, search_tool) -> None:
    candidates = []
    
    # Tier 1: Official website
    website = entity.get("website") or ""
    if website:
        if not website.startswith("http"):
            website = "http://" + website
        candidates.append(website)
        
    # Tier 2: Web-scraped venue page
    name = entity.get("name", "")
    venue_url = ""
    if name:
        search_query = f"{name} {user_city}".strip()
        try:
            search_res = await search_tool._fetch_and_rank(search_query, limit=1)
            if search_res:
                venue_url = search_res[0].get("url") or ""
                if venue_url and venue_url not in candidates:
                    candidates.append(venue_url)
        except Exception as exc:
            print("search failed during image enrichment for", name, exc)
            
    # Tier 3: Static source link
    source_url = entity.get("source_url") or ""
    if source_url and source_url not in candidates:
        candidates.append(source_url)

    print(f"Candidates for {name}: {candidates}")

    imgs = []
    for url in candidates:
        # Avoid scraping openstreetmap/google maps websites directly as they don't have venue pictures in the html structure
        if "openstreetmap.org" in url or "google.com/maps" in url:
            continue
            
        # 1. Try static httpx
        try:
            res = await asyncio.wait_for(
                scrape_tool._scrape_httpx(url),
                timeout=5.0
            )
            if res and res.get("images"):
                filtered = [img for img in res["images"] if _is_valid_image(img)]
                if filtered:
                    imgs = filtered
                    print(f"-> Found {len(imgs)} valid images via static scrape for {url}")
                    break
        except Exception as exc:
            print(f"-> Static scrape failed for {url}: {exc}")
            
        # 2. Try nodriver
        try:
            res = await asyncio.wait_for(
                scrape_tool._scrape_nodriver(url),
                timeout=10.0
            )
            if res and res.get("images"):
                filtered = [img for img in res["images"] if _is_valid_image(img)]
                if filtered:
                    imgs = filtered
                    print(f"-> Found {len(imgs)} valid images via nodriver for {url}")
                    break
        except Exception as exc:
            print(f"-> Nodriver failed for {url}: {exc}")

    # Fallback to DDG Image Search
    if not imgs and name:
        search_query = f"{name} {user_city}".strip()
        print(f"-> Falling back to DDG Image search for {name}...")
        try:
            imgs = await _fetch_ddg_images(search_query, limit=3)
            print(f"-> Found {len(imgs)} images via DDG search for {name}")
        except Exception as exc:
            print(f"-> DDG image search failed for {name}: {exc}")

    if imgs:
        entity["images"] = imgs[:3]

async def main():
    scrape_tool = WebScrapeTool()
    search_tool = WebSearchTool()
    entities = [
        {
            "name": "Old House Cafe",
            "website": "https://www.facebook.com/OldHouseCafeNP/",
            "source_url": "https://www.openstreetmap.org/node/1",
        },
        {
            "name": "Annapurna Cafe",
            "website": "",
            "source_url": "https://www.openstreetmap.org/node/2",
        }
    ]
    
    await asyncio.gather(*[_fetch_one(e, "Kathmandu", scrape_tool, search_tool) for e in entities])
    print("\nResults:")
    for e in entities:
        print(f"Name: {e['name']} | Images: {e.get('images')}")

if __name__ == "__main__":
    asyncio.run(main())
