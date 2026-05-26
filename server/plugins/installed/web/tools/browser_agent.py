"""
nodriver-based browser agent for structured entity searches.

Architecture
────────────
SITE_REGISTRY maps every intent to an ordered list of site adapters.
BrowserAgent.run() picks adapters by priority group, runs the first group
in parallel (bounded semaphore), falls back to next group only if current
returns nothing. Each adapter uses nodriver (real headless Chrome) which
bypasses Cloudflare and other bot detection.

Key differences from the old Playwright approach:
  - nodriver uses a real Chrome binary — no webdriver fingerprint leakage
  - Images are enabled (Chrome renders them), so entity cards get real photos
  - DOM extraction uses single page.evaluate() JS calls — fewer round-trips
  - Browser instances are created and stopped per-adapter (no shared context)

Progress events (tool_progress)
────────────────────────────────
  browser_start    → "Opening live browser session..."
  priority_group   → "Trying hostelworld…"
  site_navigating  → "Navigating to Hostelworld.com..."
  site_loaded      → "Hostelworld loaded — scanning listings..."
  cards_found      → "Found 18 hotels on Hostelworld"
  site_timeout     → "hostelworld took too long — skipping"
  site_error       → "hostelworld encountered an error — skipping"
  browser_empty    → "Browser agent found no results — falling back"
  complete         → "Done — 12 hotels with live reviews"

Deferred adapters (OpenCLI transactional)
──────────────────────────────────────────
booking, agoda, tripadvisor, makemytrip, zomato etc. require the user's
real Chrome session with authenticated state. These are preserved as
commented templates for future OpenCLI book_hotel / book_appointment tools.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

_log = logging.getLogger(__name__)

# ── Limits ───────────────────────────────────────────────────────────────────
_ADAPTER_TIMEOUT_S   = 35.0   # wall-clock cap per site adapter
_REVIEW_TIMEOUT_S    = 20.0   # wall-clock cap per review-fetch
_MAX_PARALLEL        = 2      # concurrent Chrome instances (RAM budget)
_MAX_IMAGES          = 10     # images per entity
_MAX_REVIEWS         = 8      # reviews per entity
_MAX_REVIEW_CHARS    = 320    # cap each review text length
_TOP_N_FOR_REVIEWS   = 5      # only fetch deep reviews for the best-rated entities

# ── Emit type alias ───────────────────────────────────────────────────────────
EmitFn = Callable[..., Coroutine[Any, Any, None]]


# ══════════════════════════════════════════════════════════════════════════════
# Site registry
# ══════════════════════════════════════════════════════════════════════════════

SITE_REGISTRY: Dict[str, List[Dict[str, Any]]] = {
    "hotel_search": [
        {"name": "hostelworld", "priority": 1},
    ],
    "product_search": [
        {"name": "ebay",     "priority": 1},
        {"name": "flipkart", "priority": 1},
    ],
    # restaurant_search, local_service: no working headless adapters yet
    # (deferred to OpenCLI transactional tools)
}

# Populated after adapter functions are defined (see bottom of file)
_ADAPTER_FN_MAP: Dict[str, Any] = {}


# ══════════════════════════════════════════════════════════════════════════════
# Public interface
# ══════════════════════════════════════════════════════════════════════════════

class BrowserAgent:
    """
    Priority-grouped browser adapters with live progress events.

    Usage:
        entities, sources = await BrowserAgent.run(
            intent="hotel_search",
            location="Kathmandu, Bagmati Province",
            query="budget hotels kathmandu",
            max_results=10,
            user_id="u_123",
            task_id="t_abc",
        )
    """

    @classmethod
    async def run(
        cls,
        intent: str,
        location: str,
        query: str,
        max_results: int = 10,
        user_id: str = "",
        task_id: str = "",
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        adapters = SITE_REGISTRY.get(intent, [])
        if not adapters:
            return [], []

        _loc_parts = [p.strip() for p in (location or "").split(",") if p.strip()]
        if len(_loc_parts) >= 2:
            city = f"{_loc_parts[0]}, {_loc_parts[-1]}"
        elif _loc_parts:
            city = _loc_parts[0]
        else:
            city = query

        emit = _make_emit(user_id, task_id)
        intent_label = intent.replace("_", " ")
        await emit("browser_start",
                   f"Opening live browser session for {intent_label}…",
                   intent=intent, city=city)

        # Group by priority — run groups sequentially, within each group parallel.
        priority_groups: Dict[int, List[Tuple[str, Any]]] = {}
        for entry in adapters:
            fn = _ADAPTER_FN_MAP.get(entry["name"])
            if fn:
                p = entry["priority"]
                priority_groups.setdefault(p, []).append((entry["name"], fn))

        sem = asyncio.Semaphore(_MAX_PARALLEL)

        async def _run_one(name: str, fn: Any) -> Tuple[str, List[Dict], List[Dict]]:
            async with sem:
                try:
                    ents, srcs = await asyncio.wait_for(
                        fn(city, query, max_results, emit),
                        timeout=_ADAPTER_TIMEOUT_S,
                    )
                    return name, ents, srcs
                except asyncio.TimeoutError:
                    await emit("site_timeout", f"{name} took too long — skipping", site=name)
                except Exception as exc:
                    _log.warning("BrowserAgent: %s failed: %s", name, exc)
                    await emit("site_error", f"{name} encountered an error — skipping", site=name)
                return name, [], []

        all_entities: List[Dict] = []
        all_sources:  List[Dict] = []
        seen_src: set = set()
        sites_with_results: List[str] = []

        for priority in sorted(priority_groups.keys()):
            group = priority_groups[priority]
            group_names = ", ".join(n for n, _ in group)
            await emit("priority_group", f"Trying {group_names}…",
                       priority=priority, sites=[n for n, _ in group])

            group_results = await asyncio.gather(*[_run_one(n, fn) for n, fn in group])

            for name, ents, srcs in group_results:
                if ents:
                    sites_with_results.append(name)
                all_entities.extend(ents)
                for s in srcs:
                    url = s.get("url", "")
                    if url and url not in seen_src:
                        seen_src.add(url)
                        all_sources.append(s)

            if all_entities:
                break

        if not all_entities:
            await emit("browser_empty", "Browser agent found no results — falling back")
            return [], []

        if len(sites_with_results) > 1:
            await emit("merging",
                       f"Cross-referencing results from {', '.join(sites_with_results)}…",
                       sites=sites_with_results)
        merged = _merge_entities(all_entities)

        total_reviews = sum(len(e.get("reviews") or []) for e in merged)
        await emit("complete",
                   f"Done — {len(merged[:max_results * 2])} results",
                   count=len(merged))

        return merged[:max_results * 2], all_sources


# ══════════════════════════════════════════════════════════════════════════════
# Progress emitter
# ══════════════════════════════════════════════════════════════════════════════

def _make_emit(user_id: str, task_id: str) -> EmitFn:
    async def _emit(stage: str, message: str, **extra: Any) -> None:
        if not user_id:
            return
        try:
            from app.socket.log_stream import emit_spark_log
            await emit_spark_log(
                user_id, "tool_progress",
                task_id=task_id,
                tool_name="browser_agent",
                payload={"stage": stage, "message": message, **extra},
            )
        except Exception:
            pass
    return _emit


# ══════════════════════════════════════════════════════════════════════════════
# nodriver browser factory
# ══════════════════════════════════════════════════════════════════════════════

async def _make_browser(headless: bool = True) -> Any:
    """
    Launch a nodriver-controlled real Chrome instance.
    Images are enabled (unlike old Playwright path) so entity cards get real photos.
    """
    import nodriver as uc
    browser = await uc.start(headless=headless)
    return browser


async def _dismiss_popups(page: Any, button_texts: List[str]) -> None:
    """Click dismiss buttons by visible text using nodriver's find()."""
    for text in button_texts:
        try:
            btn = await page.find(text, best_match=True, timeout=2)
            if btn:
                await btn.click()
                await asyncio.sleep(0.5)
                return
        except Exception:
            pass


async def _wait_for_selector(page: Any, selectors: List[str], timeout_s: float = 10.0) -> bool:
    """Poll page until one selector matches or timeout."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        for sel in selectors:
            try:
                els = await page.query_selector_all(sel)
                if els:
                    return True
            except Exception:
                pass
        await asyncio.sleep(0.8)
    return False


# ══════════════════════════════════════════════════════════════════════════════
# Entity merging
# ══════════════════════════════════════════════════════════════════════════════

def _merge_entities(entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Dict[str, Dict[str, Any]] = {}
    for entity in entities:
        key = _norm_name(entity.get("name", ""))
        if not key:
            continue
        if key not in seen:
            seen[key] = dict(entity)
            seen[key].setdefault("images", [])
            seen[key].setdefault("reviews", [])
        else:
            existing = seen[key]
            combined_imgs = list(dict.fromkeys(
                (existing.get("images") or []) + (entity.get("images") or [])
            ))
            existing["images"] = combined_imgs[:_MAX_IMAGES]
            existing_reviews = existing.get("reviews") or []
            new_reviews = entity.get("reviews") or []
            existing["reviews"] = (existing_reviews + new_reviews)[:_MAX_REVIEWS]
            for field, value in entity.items():
                if field in ("images", "reviews"):
                    continue
                if field == "review_count" and value:
                    existing[field] = max(int(existing.get(field) or 0), int(value or 0))
                elif not existing.get(field):
                    existing[field] = value
    return list(seen.values())


def _norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


# ══════════════════════════════════════════════════════════════════════════════
# Value parsers
# ══════════════════════════════════════════════════════════════════════════════

def _parse_float(text: str) -> Optional[float]:
    if not text:
        return None
    m = re.search(r"[\d]+(?:[.,]\d+)?", text.replace(",", "."))
    try:
        return float(m.group().replace(",", ".")) if m else None
    except ValueError:
        return None


def _parse_int(text: str) -> Optional[int]:
    if not text:
        return None
    nums = re.findall(r"\d+", text.replace(",", ""))
    try:
        return int(nums[-1]) if nums else None
    except ValueError:
        return None


def _clean_price(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


# ══════════════════════════════════════════════════════════════════════════════
# Hotel adapters
# ══════════════════════════════════════════════════════════════════════════════

# Country → continent/country path segment for Hostelworld URLs
_HW_PATH: Dict[str, str] = {
    "nepal": "asia/nepal",
    "india": "asia/india",
    "thailand": "asia/thailand",
    "indonesia": "asia/indonesia",
    "vietnam": "asia/vietnam",
    "japan": "asia/japan",
    "china": "asia/china",
    "cambodia": "asia/cambodia",
    "philippines": "asia/philippines",
    "malaysia": "asia/malaysia",
    "sri lanka": "asia/sri-lanka",
    "portugal": "europe/portugal",
    "spain": "europe/spain",
    "france": "europe/france",
    "germany": "europe/germany",
    "italy": "europe/italy",
    "uk": "europe/united-kingdom",
    "united kingdom": "europe/united-kingdom",
    "netherlands": "europe/netherlands",
    "czechia": "europe/czech-republic",
    "czech republic": "europe/czech-republic",
    "usa": "north-america/united-states",
    "united states": "north-america/united-states",
    "canada": "north-america/canada",
    "mexico": "central-america/mexico",
    "brazil": "south-america/brazil",
    "argentina": "south-america/argentina",
    "colombia": "south-america/colombia",
    "peru": "south-america/peru",
    "australia": "pacific/australia",
    "new zealand": "pacific/new-zealand",
}

# Province/state/region → country for resolving current_location output
# (current_location returns "City, Province" not "City, Country")
_REGION_TO_COUNTRY: Dict[str, str] = {
    "bagmati province": "nepal", "bagmati": "nepal",
    "gandaki province": "nepal", "gandaki": "nepal",
    "lumbini province": "nepal", "lumbini": "nepal",
    "koshi province": "nepal", "koshi": "nepal",
    "madhesh province": "nepal", "madhesh": "nepal",
    "sudurpashchim province": "nepal", "sudurpashchim": "nepal",
    "karnali province": "nepal", "karnali": "nepal",
    "maharashtra": "india", "delhi": "india", "new delhi": "india",
    "karnataka": "india", "tamil nadu": "india", "kerala": "india",
    "west bengal": "india", "rajasthan": "india", "goa": "india",
    "uttar pradesh": "india", "telangana": "india", "andhra pradesh": "india",
    "gujarat": "india", "madhya pradesh": "india", "punjab": "india",
    "haryana": "india", "himachal pradesh": "india", "uttarakhand": "india",
    "bangkok": "thailand", "chiang mai": "thailand",
    "bali": "indonesia", "jakarta": "indonesia",
    "ho chi minh": "vietnam", "hanoi": "vietnam",
    "tokyo": "japan", "osaka": "japan", "kyoto": "japan",
    "queensland": "australia", "new south wales": "australia",
    "victoria": "australia", "western australia": "australia",
    "california": "usa", "new york": "usa", "texas": "usa", "florida": "usa",
    "ontario": "canada", "british columbia": "canada", "quebec": "canada",
    "england": "uk", "scotland": "uk", "wales": "uk",
    "île-de-france": "france", "ile-de-france": "france",
    "catalonia": "spain", "andalusia": "spain",
    "bavaria": "germany", "lombardy": "italy", "lazio": "italy",
}


def _hw_url(city: str) -> str:
    """Build the correct Hostelworld listing URL for a city."""
    parts = [p.strip().lower() for p in city.split(",") if p.strip()]
    city_slug = re.sub(r"[^a-z0-9]+", "-", parts[0]).strip("-")

    # Try the last part as country, then resolve region → country
    country_key = parts[-1] if len(parts) >= 2 else ""
    if country_key not in _HW_PATH:
        country_key = _REGION_TO_COUNTRY.get(country_key, "")
    path_seg = _HW_PATH.get(country_key, "")

    if path_seg:
        return f"https://www.hostelworld.com/st/hostels/{path_seg}/{city_slug}/"
    return f"https://www.hostelworld.com/st/hostels/{city_slug}/"


async def _hostelworld(city: str, query: str, max_results: int, emit: EmitFn) -> Tuple[List[Dict], List[Dict]]:
    url = _hw_url(city)
    _log.info("hostelworld: city=%r → url=%s", city, url)
    try:
        browser = await _make_browser()
    except Exception as exc:
        _log.warning("hostelworld: failed to launch browser: %s", exc)
        return [], []
    try:
        await emit("site_navigating", "Navigating to Hostelworld.com…", site="hostelworld")
        page = await browser.get(url)
        await asyncio.sleep(4)

        # Dismiss cookie / popup banners
        await _dismiss_popups(page, ["Accept", "Accept all", "OK", "Got it"])

        # Scroll to load more listings
        for i in range(3):
            await page.evaluate(f"window.scrollTo(0, {(i + 1) * 700})")
            await asyncio.sleep(1)

        # Extract all property cards in a single JS call
        raw = await page.evaluate("""JSON.stringify((() => {
            const results = [];

            // Strategy 1: links to individual hostel detail pages
            const detailLinks = document.querySelectorAll('a[href*="/pwa/hosteldetails"], a[href*="/hostels/"][href*="/p/"]');
            if (detailLinks.length > 0) {
                for (const a of detailLinks) {
                    const card = a.closest('[class*="property"], [class*="card"], [class*="listing"], article, li') || a.parentElement;
                    const text = card ? card.innerText : a.innerText;
                    const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);
                    const imgEl = card ? card.querySelector('img[src]') : null;
                    results.push({
                        name: lines[0] || '',
                        lines: lines.slice(0, 10),
                        href: a.href,
                        img: imgEl ? (imgEl.currentSrc || imgEl.src) : '',
                    });
                    if (results.length >= 20) break;
                }
                return results;
            }

            // Strategy 2: any link containing hostel/property in href path
            const allLinks = document.querySelectorAll('a[href]');
            for (const a of allLinks) {
                const href = a.href || '';
                if (!href.includes('/hostel') && !href.includes('/property')) continue;
                if (href.includes('hostelworld.com') && (href.includes('/p/') || href.match(/\/[a-z-]+\/[a-z-]+\/[a-z-]+\/[a-z-]/))) {
                    const text = a.innerText?.trim();
                    if (!text || text.length < 5 || text.length > 300) continue;
                    const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);
                    results.push({ name: lines[0] || '', lines, href, img: '' });
                    if (results.length >= 20) break;
                }
            }
            return results;
        })())""")

        cards_data: List[Dict] = []
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, list):
                cards_data = parsed
        except Exception:
            pass

        if not cards_data:
            await emit("site_empty", "Hostelworld: no listings found", site="hostelworld")
            return [], []

        await emit("site_loaded", f"Hostelworld loaded — scanning {len(cards_data)} listings…", site="hostelworld")

        entities: List[Dict] = []
        for card in cards_data[:max_results]:
            try:
                name = card.get("name", "").strip()
                if not name or len(name) < 3:
                    continue
                lines: List[str] = card.get("lines", [])
                href = card.get("href", "")
                img = card.get("img", "")

                # Parse price and rating from text lines
                price = ""
                rating_raw = ""
                for line in lines:
                    if not price and re.search(r"[$€£₹¥₩]|from|per night|dorm", line, re.I):
                        price = line.strip()
                    if not rating_raw and re.search(r"\b\d+\.\d\b|\bsuperb\b|\bfabulous\b|\bwonderful\b", line, re.I):
                        rating_raw = line.strip()

                booking_url = href if href.startswith("http") else (f"https://www.hostelworld.com{href}" if href else url)
                images = [img] if (img and img.startswith("http") and "data:" not in img and len(img) > 10) else []

                e: Dict[str, Any] = {
                    "type": "hotel", "name": name, "location": city,
                    "source_url": booking_url, "booking_url": booking_url,
                    "amenities": [], "images": images, "reviews": [],
                }
                if price:
                    e["price_per_night"] = _clean_price(price)
                r = _parse_float(rating_raw)
                if r is not None and r <= 10:
                    e["rating"] = min(r, 10.0)
                entities.append(e)
            except Exception as exc:
                _log.debug("hostelworld card: %s", exc)

        await emit("cards_found", f"Found {len(entities)} hotels on Hostelworld",
                   site="hostelworld", count=len(entities))
        return entities, [{"url": url, "title": f"Hostelworld – {city}"}]
    finally:
        try:
            browser.stop()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# Product adapters
# ══════════════════════════════════════════════════════════════════════════════

async def _ebay(city: str, query: str, max_results: int, emit: EmitFn) -> Tuple[List[Dict], List[Dict]]:
    url = f"https://www.ebay.com/sch/i.html?_nkw={quote_plus(query)}&_sop=12"
    browser = await _make_browser()
    try:
        await emit("site_navigating", "Navigating to eBay…", site="ebay")
        page = await browser.get(url)
        await asyncio.sleep(3)

        found = await _wait_for_selector(page, [".s-item"], timeout_s=8)
        if not found:
            await emit("site_empty", "eBay: no listings found", site="ebay")
            return [], []

        await emit("site_loaded", "eBay loaded — scanning product listings…", site="ebay")

        raw = await page.evaluate("""JSON.stringify((() => {
            const items = document.querySelectorAll('.s-item');
            const results = [];
            for (const item of items) {
                const title = item.querySelector('.s-item__title')?.innerText?.trim() || '';
                if (!title || title === 'Shop on eBay') continue;
                const price = item.querySelector('.s-item__price')?.innerText?.trim() || '';
                const rating = item.querySelector('.x-star-rating')?.innerText?.trim() || '';
                const reviews = item.querySelector('.s-item__reviews-count')?.innerText?.trim() || '';
                const href = item.querySelector('a.s-item__link')?.getAttribute('href') || '';
                const img = item.querySelector('img[src]')?.src || '';
                results.push({ title, price, rating, reviews, href, img });
                if (results.length >= 20) break;
            }
            return results;
        })())""")

        cards_data = json.loads(raw) if isinstance(raw, str) else (raw or [])
        entities: List[Dict] = []

        for card in cards_data[:max_results]:
            name = card.get("title", "").strip()
            if not name:
                continue
            href = card.get("href", "")
            img = card.get("img", "")

            e: Dict[str, Any] = {
                "type": "product", "name": name,
                "source_url": href, "buy_url": href,
                "features": [],
                "images": [img] if (img and img.startswith("http")) else [],
                "reviews": [],
            }
            if card.get("price"):
                e["price"] = _clean_price(card["price"])
            r = _parse_float(card.get("rating", ""))
            if r is not None:
                e["rating"] = r
            rc = _parse_int(card.get("reviews", ""))
            if rc:
                e["review_count"] = rc
            entities.append(e)
            if len(entities) >= max_results:
                break

        await emit("cards_found", f"Found {len(entities)} products on eBay",
                   site="ebay", count=len(entities))
        return entities, [{"url": url, "title": f"eBay – {query}"}]
    finally:
        try:
            browser.stop()
        except Exception:
            pass


async def _flipkart(city: str, query: str, max_results: int, emit: EmitFn) -> Tuple[List[Dict], List[Dict]]:
    url = f"https://www.flipkart.com/search?q={quote_plus(query)}&sort=popularity"
    browser = await _make_browser()
    try:
        await emit("site_navigating", "Navigating to Flipkart…", site="flipkart")
        page = await browser.get(url)
        await asyncio.sleep(3)

        # Dismiss login popup
        await _dismiss_popups(page, ["✕", "Close", "×"])

        found = await _wait_for_selector(page, ["._1AtVbE", "._2kHMtA", "[class*='product']"], timeout_s=8)
        if not found:
            await emit("site_empty", "Flipkart: no listings found", site="flipkart")
            return [], []

        await emit("site_loaded", "Flipkart loaded — scanning product listings…", site="flipkart")

        raw = await page.evaluate("""JSON.stringify((() => {
            // Try multiple card selectors
            let cards = document.querySelectorAll('._1AtVbE:has(a), ._2kHMtA');
            if (cards.length === 0) cards = document.querySelectorAll('[data-id], [class*="productCard"]');
            const results = [];
            for (const card of cards) {
                const name = card.querySelector('._4rR01T, .IRpwTa, a[title]')?.innerText?.trim()
                          || card.querySelector('h2, h3')?.innerText?.trim() || '';
                if (!name) continue;
                const price = card.querySelector('._30jeq3, ._1_WHN1')?.innerText?.trim() || '';
                const rating = card.querySelector('._3LWZlK')?.innerText?.trim() || '';
                const reviews = card.querySelector('._2_R_DZ span')?.innerText?.trim() || '';
                const link = card.querySelector("a[href*='/p/']");
                const href = link ? 'https://www.flipkart.com' + link.getAttribute('href') : '';
                const img = card.querySelector('img[src]')?.src || '';
                results.push({ name, price, rating, reviews, href, img });
                if (results.length >= 20) break;
            }
            return results;
        })())""")

        cards_data = json.loads(raw) if isinstance(raw, str) else (raw or [])
        entities: List[Dict] = []

        for card in cards_data[:max_results]:
            name = card.get("name", "").strip()
            if not name:
                continue
            href = card.get("href", "")
            img = card.get("img", "")

            e: Dict[str, Any] = {
                "type": "product", "name": name,
                "source_url": href, "buy_url": href,
                "features": [],
                "images": [img] if (img and img.startswith("http") and "data:" not in img) else [],
                "reviews": [],
            }
            if card.get("price"):
                e["price"] = _clean_price(card["price"])
            r = _parse_float(card.get("rating", ""))
            if r is not None:
                e["rating"] = r
            rc = _parse_int(card.get("reviews", ""))
            if rc:
                e["review_count"] = rc
            entities.append(e)

        await emit("cards_found", f"Found {len(entities)} products on Flipkart",
                   site="flipkart", count=len(entities))
        return entities, [{"url": url, "title": f"Flipkart – {query}"}]
    finally:
        try:
            browser.stop()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# Deferred adapters — preserved for future OpenCLI transactional tools
# These require a real authenticated browser session (OpenCLI drives the user's
# own Chrome) and are NOT suitable for headless anonymous scraping.
# ══════════════════════════════════════════════════════════════════════════════

# async def _booking(city, query, max_results, emit): ...   → book_hotel OpenCLI tool
# async def _agoda(city, query, max_results, emit): ...     → book_hotel OpenCLI tool
# async def _tripadvisor_hotels(...): ...                   → book_hotel OpenCLI tool
# async def _makemytrip(...): ...                           → book_hotel OpenCLI tool
# async def _zomato(...): ...                               → book_restaurant OpenCLI tool
# async def _tripadvisor_restaurants(...): ...              → book_restaurant OpenCLI tool
# async def _justdial(...): ...                             → local_service OpenCLI tool
# async def _sulekha(...): ...                              → local_service OpenCLI tool
# async def _aliexpress(...): ...                           → product OpenCLI tool


# ── Late-bind adapter functions into the registry ─────────────────────────────
_ADAPTER_FN_MAP = {
    "hostelworld": _hostelworld,
    "ebay":        _ebay,
    "flipkart":    _flipkart,
}
