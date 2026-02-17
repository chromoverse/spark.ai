"""
pip install httpx trafilatura playwright
playwright install chromium
"""
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura
from trafilatura.settings import use_config

from app.agent.shared.tools.base import BaseTool, ToolOutput

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com/users/"

# Trafilatura config: be generous, grab everything
_trafilatura_cfg = use_config()
_trafilatura_cfg.set("DEFAULT", "EXTRACTION_TIMEOUT", "0")

# Sites that need a real browser (JS-rendered)
JS_DOMAINS = {
    "airbnb.com", "booking.com", "expedia.com", "hotels.com",
    "marriott.com", "hilton.com", "tripadvisor.com", "fandango.com",
    "imdb.com", "instagram.com", "twitter.com", "x.com", "linkedin.com",
    "bbc.com", "bbc.co.uk", "weather-atlas.com", "theweathernetwork.com",
    "meteum.ai",
}

API_DOMAINS = {"github.com"}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


class WebScrapeTool(BaseTool):
    """
    Fast, reliable web scraper.

    Strategy (per URL):
      1. GitHub → REST API
      2. Known JS-heavy domain → async Playwright (single shared browser per call)
      3. Everything else → httpx (async) + trafilatura (smart extraction)
         with automatic Playwright fallback if text is too short.

    Params schema  : base_links (array, required), query (str), max_results (int, default 10)
    Output schema  : { results: array, total_results: int, search_time_ms: float }
    """

    def get_tool_name(self) -> str:
        return "web_scrape"

    def __init__(self, max_chars: int = 5000, timeout: int = 15, max_workers: int = 5):
        super().__init__()
        self.max_chars = max_chars
        self.timeout = timeout
        self.max_workers = max_workers

    # ------------------------------------------------------------------
    # BaseTool entry point
    # ------------------------------------------------------------------

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        start_ms = time.time() * 1000

        base_links: List[str] = self.get_input(inputs, "base_links", [])
        max_results: int = self.get_input(inputs, "max_results", 10)
        _query: Optional[str] = self.get_input(inputs, "query", None)

        if not base_links:
            return ToolOutput(success=False, data={}, error="'base_links' must be a non-empty array.")

        results = await self._scrape_all(base_links[:max_results])

        elapsed = round((time.time() * 1000) - start_ms, 2)
        return ToolOutput(
            success=True,
            data={
                "results": results,
                "total_results": len(results),
                "search_time_ms": elapsed,
            },
        )

    # ------------------------------------------------------------------
    # Parallel scraping — fully async, no threads
    # ------------------------------------------------------------------

    async def _scrape_all(self, urls: List[str]) -> List[Dict[str, Any]]:
        sem = asyncio.Semaphore(self.max_workers)

        async def bounded(url: str) -> Dict[str, Any]:
            async with sem:
                return await self._scrape_one(url)

        return await asyncio.gather(*[bounded(u) for u in urls])

    async def _scrape_one(self, url: str) -> Dict[str, Any]:
        try:
            domain = _extract_domain(url)
            if any(d in domain for d in API_DOMAINS):
                data = await self._scrape_github(url)
            elif any(d in domain for d in JS_DOMAINS):
                data = await self._scrape_playwright(url)
            else:
                data = await self._scrape_httpx(url)
            return {"url": url, "success": True, **data}
        except Exception as exc:
            logger.error(f"Error scraping {url}: {exc}")
            return {"url": url, "success": False, "title": "", "text": str(exc), "links": []}

    # ------------------------------------------------------------------
    # Strategy 1: fast httpx + trafilatura (static / SSR sites)
    # ------------------------------------------------------------------

    async def _scrape_httpx(self, url: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(
            headers=_HEADERS, timeout=self.timeout, follow_redirects=True
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text

        text = trafilatura.extract(
            html,
            config=_trafilatura_cfg,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
            favor_recall=True,   # grab more, not less
        ) or ""

        # Too little? Fall back to Playwright
        if len(text.strip()) < 150:
            logger.info(f"httpx got too little text for {url} — falling back to Playwright")
            return await self._scrape_playwright(url)

        meta = trafilatura.extract_metadata(html)
        title = (meta.title if meta else "") or ""
        links = _extract_links(html, url)
        return {"title": title, "text": text[: self.max_chars], "links": links[:50]}

    # ------------------------------------------------------------------
    # Strategy 2: Playwright — async, single browser per call
    # ------------------------------------------------------------------

    async def _scrape_playwright(self, url: str) -> Dict[str, Any]:
        try:
            from playwright.async_api import async_playwright
            from playwright.async_api import TimeoutError as PwTimeout
        except ImportError:
            raise RuntimeError(
                "playwright not installed. Run:\n"
                "  pip install playwright\n"
                "  playwright install chromium"
            )

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--blink-settings=imagesEnabled=false",
                ],
            )
            context = await browser.new_context(
                user_agent=_HEADERS["User-Agent"],
                java_script_enabled=True,
                bypass_csp=True,
            )
            page = await context.new_page()

            # Block heavy assets for speed
            await page.route(
                "**/*.{png,jpg,jpeg,gif,webp,svg,ico,woff,woff2,ttf,mp4,mp3}",
                lambda route: route.abort(),
            )

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout * 1000)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.5)")
                await asyncio.sleep(1.5)
            except PwTimeout:
                logger.warning(f"Playwright load timed out for {url}, extracting partial content")

            html = await page.content()
            title = await page.title()
            await browser.close()

        # Trafilatura still does the extraction — works great on rendered HTML too
        text = trafilatura.extract(
            html,
            config=_trafilatura_cfg,
            include_tables=True,
            favor_recall=True,
        ) or ""

        if len(text.strip()) < 100:
            text = _bs4_fallback(html)

        links = _extract_links(html, url)
        return {"title": title, "text": text[: self.max_chars], "links": links[:50]}

    # ------------------------------------------------------------------
    # Strategy 3: GitHub REST API
    # ------------------------------------------------------------------

    async def _scrape_github(self, url: str) -> Dict[str, Any]:
        username = url.strip("/").split("/")[-1]
        async with httpx.AsyncClient(headers=_HEADERS, timeout=self.timeout) as client:
            resp = await client.get(f"{GITHUB_API_BASE}{username}/repos")
            resp.raise_for_status()
            repos = resp.json()

        names = [r["name"] for r in repos[:50]]
        links = [r["html_url"] for r in repos[:50]]
        text = f"GitHub user '{username}' has {len(repos)} repos: " + ", ".join(names)
        return {"title": f"GitHub Profile: {username}", "text": text[: self.max_chars], "links": links}


# ---------------------------------------------------------------------------
# Stateless helpers
# ---------------------------------------------------------------------------

def _extract_domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def _extract_links(html: str, base_url: str) -> List[str]:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    seen: List[str] = []
    for a in soup.find_all("a", href=True):
        href: str = str(a["href"])
        full = href if href.startswith("http") else urljoin(base_url, href)
        if full.startswith("http") and full not in seen:
            seen.append(full)
    return seen


def _bs4_fallback(html: str) -> str:
    """Last-resort plain-text extraction when trafilatura finds nothing."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "iframe"]):
        tag.decompose()
    parts = [
        el.get_text(" ", strip=True)
        for el in soup.select("p, li, td, h1, h2, h3, h4")
        if len(el.get_text(strip=True)) > 40
    ]
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    async def main() -> None:
        tool = WebScrapeTool(max_chars=3000)
        result = await tool.execute({
            "base_links": [
                "https://www.weather-atlas.com/en/nepal/kathmandu",
                "https://www.theweathernetwork.com/en/city/np/pradesh-2/janakpur/hourly",
                "https://github.com/torvalds",
                "https://www.bbc.com/weather/1283240",
            ],
            "max_results": 4,
        })

        print(f"Success: {result.success}  |  Time: {result.data['search_time_ms']} ms")
        for item in result.data["results"]:
            print(f"\n{'─'*60}")
            print(f"URL  : {item['url']}")
            print(f"OK   : {item['success']}")
            print(f"Title: {item.get('title', '')[:80]}")
            print(f"Text : {item.get('text', '')[:400]}")

    asyncio.run(main())