"""Daraz Nepal product listing provider.

Why a dedicated provider
────────────────────────
The generic DDGS+scrape+LLM-extract path returns one or two thin product
entities for Daraz queries — the catalog page is a JS shell and the
scrape captures mostly chrome, so the LLM has nothing to work with.

Daraz/Lazada exposes the catalog as JSON via the same URL with
``?ajax=true``. One HTTP request gives us 40+ structured products with
name, current/original price, image, rating, review count, brand,
location — no LLM call, no DOM parsing, no scraping fragility.

Endpoint
────────
``https://www.daraz.com.np/catalog/?q=<query>&ajax=true&page=<n>``

Returns ``{"templates": ..., "mods": {"listItems": [...], ...}, ...}``
where each list item carries the fields we map below. Field names are
stable enough to be load-bearing — they ship from Alibaba's catalog
service and have been in this shape across multiple Daraz layout
versions.

Product URL synthesis
─────────────────────
listItems don't carry a clickable URL — the Daraz frontend builds it
from ``itemId``/``skuId``. The canonical short form
``https://www.daraz.com.np/products/-i<itemId>-s<skuId>.html`` redirects
to the full slug page, which is what we want for the Buy flow.

Failure mode
────────────
Best-effort. Returns ``[]`` on any HTTP/JSON failure or layout change so
the caller falls back to the generic entity_search path. We never raise.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import httpx

logger = logging.getLogger(__name__)


_BASE = "https://www.daraz.com.np"
_AJAX_URL = _BASE + "/catalog/?q={q}&ajax=true&page={page}"

# Realistic Chrome UA + XHR markers — Daraz returns an HTML shell to bot-
# shaped UAs and only ships the JSON payload when it thinks an actual
# browser is fetching the ajax variant.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
}

_TIMEOUT_S = 12.0


def _build_product_url(item: Dict[str, Any]) -> str:
    """Synthesize a product detail URL from a listItem.

    ``/products/-i<itemId>-s<skuId>.html`` redirects to the slugified
    canonical page. Both ID fields are always present on real products.
    """
    item_id = item.get("itemId") or item.get("nid")
    sku_id = item.get("skuId")
    if item_id and sku_id:
        return f"{_BASE}/products/-i{item_id}-s{sku_id}.html"
    if item_id:
        return f"{_BASE}/products/-i{item_id}.html"
    return ""


def _coerce_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


def _coerce_int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _normalize(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    name = item.get("name")
    if not isinstance(name, str) or not name.strip():
        return None

    entity: Dict[str, Any] = {
        "type": "product",
        "name": name.strip(),
    }

    # ``priceShow`` is the customer-visible string ("Rs. 555"); ``price``
    # is the numeric form. Prefer the formatted one for cards.
    price_show = item.get("priceShow") or item.get("price")
    if price_show:
        entity["price"] = str(price_show)
    orig_show = item.get("originalPriceShow") or item.get("originalPrice")
    if orig_show and str(orig_show) != str(price_show or ""):
        entity["original_price"] = str(orig_show)

    image = item.get("image")
    if isinstance(image, str) and image:
        entity["images"] = [image]

    brand = item.get("brandName")
    # Daraz uses "No Brand" as a placeholder — drop it so the UI doesn't
    # render a meaningless chip.
    if isinstance(brand, str) and brand.strip() and brand.strip().lower() != "no brand":
        entity["brand"] = brand.strip()

    rating = _coerce_float(item.get("ratingScore"))
    if rating is not None and 0 <= rating <= 5:
        entity["rating"] = round(rating, 2)

    rc = _coerce_int(item.get("review"))
    if rc is not None and rc >= 0:
        entity["review_count"] = rc

    if item.get("inStock") is False:
        entity["availability"] = "Out of stock"
    elif item.get("inStock") is True:
        entity["availability"] = "In stock"

    sold = item.get("itemSoldCntShow")
    desc_bits: List[str] = []
    if isinstance(sold, str) and sold.strip():
        desc_bits.append(sold.strip())
    loc = item.get("location")
    if isinstance(loc, str) and loc.strip():
        desc_bits.append(f"Ships from {loc.strip()}")
    discount = item.get("discount")
    if isinstance(discount, str) and discount.strip():
        desc_bits.append(discount.strip())
    if desc_bits:
        entity["description"] = " · ".join(desc_bits)

    url = _build_product_url(item)
    if url:
        entity["buy_url"] = url
        entity["source_url"] = url
    else:
        entity["source_url"] = _BASE + "/"

    return entity


async def fetch_daraz_products(
    query: str,
    *,
    limit: int = 12,
    timeout_s: float = _TIMEOUT_S,
) -> List[Dict[str, Any]]:
    """Return up to ``limit`` normalised Daraz Nepal product entities.

    Empty list on any failure — caller falls back to the generic search.
    """
    q = (query or "").strip()
    if not q:
        return []
    url = _AJAX_URL.format(q=quote_plus(q), page=1)
    headers = {**_HEADERS, "Referer": f"{_BASE}/catalog/?q={quote_plus(q)}"}
    try:
        async with httpx.AsyncClient(
            headers=headers,
            timeout=timeout_s,
            follow_redirects=True,
        ) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.info("daraz_provider: status=%d for %r", resp.status_code, q)
                return []
            # When Daraz can't serve the ajax variant (bot detection, geo
            # block, etc) it falls back to the HTML shell. Bail rather
            # than feed garbage downstream.
            ctype = resp.headers.get("content-type", "").lower()
            if "json" not in ctype:
                logger.info("daraz_provider: non-JSON content-type %r for %r", ctype, q)
                return []
            data = resp.json()
    except Exception as exc:
        logger.info("daraz_provider: fetch failed for %r: %s", q, exc)
        return []

    try:
        items = data["mods"]["listItems"]
    except (KeyError, TypeError):
        logger.info("daraz_provider: no mods.listItems in response for %r", q)
        return []
    if not isinstance(items, list):
        return []

    products: List[Dict[str, Any]] = []
    seen_ids: set = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        ident = item.get("itemId") or item.get("nid") or item.get("name")
        if ident in seen_ids:
            continue
        normalized = _normalize(item)
        if normalized is None:
            continue
        seen_ids.add(ident)
        products.append(normalized)
        if len(products) >= limit:
            break

    return products


__all__ = ["fetch_daraz_products"]
