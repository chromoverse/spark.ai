import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from typing import List, Dict, Any, Optional
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

# Selenium imports
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

from app.agent.shared.tools.base import BaseTool, ToolOutput

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# API Configuration
GITHUB_API_BASE = "https://api.github.com/users/"


class WebScrapeTool(BaseTool):
    """
    Web scraping tool that handles multiple website types including hotels,
    cinemas, social media, GitHub, etc.

    Follows the tool_registry.json schema for web_scrape:
      params:  base_links (array, required), query (string), max_results (int, default 10)
      output:  { results: array, total_results: int, search_time_ms: float }
    """

    # ------------------------------------------------------------------
    # BaseTool contract
    # ------------------------------------------------------------------

    def get_tool_name(self) -> str:
        return "web_scrape"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        start_ms = time.time() * 1000

        base_links: List[str] = self.get_input(inputs, "base_links", [])
        max_results: int = self.get_input(inputs, "max_results", 10)
        # `query` is available for future relevance-filtering; stored for extension
        _query: Optional[str] = self.get_input(inputs, "query", None)

        if not base_links:
            return ToolOutput(
                success=False,
                data={},
                error="'base_links' must be a non-empty array of URLs.",
            )

        urls_to_scrape = base_links[:max_results]
        raw_results = self._scrape_urls(urls_to_scrape, use_async=True)

        elapsed_ms = (time.time() * 1000) - start_ms

        return ToolOutput(
            success=True,
            data={
                "results": raw_results,
                "total_results": len(raw_results),
                "search_time_ms": round(elapsed_ms, 2),
            },
        )

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def __init__(self, max_chars: int = 5000, timeout: int = 20, max_workers: int = 5):
        super().__init__()
        self.max_chars = max_chars
        self.timeout = timeout
        self.max_workers = max_workers

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            }
        )

        # Site-specific Selenium configurations
        self.js_heavy_sites: Dict[str, Dict[str, Any]] = {
            "airbnb.com": {
                "wait_selector": "div[itemprop='itemListElement']",
                "wait_time": 12,
                "content_selectors": [
                    "div[itemprop='itemListElement']",
                    "div[data-testid='listing-card-title']",
                    "div.c4mnd7m",
                ],
                "extract_names": True,
            },
            "booking.com": {
                "wait_selector": "div[data-testid='property-card']",
                "wait_time": 12,
                "content_selectors": [
                    "div[data-testid='property-card']",
                    "div[data-testid='title']",
                    "h3.a7ba9e5476",
                    "div[data-testid='price-and-discounted-price']",
                ],
                "extract_names": True,
            },
            "instagram.com": {
                "wait_selector": "article",
                "wait_time": 8,
                "content_selectors": ["article"],
                "extract_names": False,
            },
            "twitter.com": {
                "wait_selector": "article[data-testid='tweet']",
                "wait_time": 8,
                "content_selectors": ["article[data-testid='tweet']"],
                "extract_names": False,
            },
            "x.com": {
                "wait_selector": "article[data-testid='tweet']",
                "wait_time": 8,
                "content_selectors": ["article[data-testid='tweet']"],
                "extract_names": False,
            },
            "linkedin.com": {
                "wait_selector": "div.feed-shared-update-v2",
                "wait_time": 8,
                "content_selectors": ["div.feed-shared-update-v2"],
                "extract_names": False,
            },
            "tripadvisor.com": {
                "wait_selector": "div.listing_title",
                "wait_time": 12,
                "content_selectors": [
                    "div.listing_title",
                    "div.prw_rup.prw_meta_hsx_responsive_listing",
                    "a.property_title",
                    "div.ui_column.is-9",
                ],
                "extract_names": True,
            },
            "expedia.com": {
                "wait_selector": "div[data-stid='lodging-card-responsive']",
                "wait_time": 10,
                "content_selectors": ["div[data-stid='lodging-card-responsive']"],
                "extract_names": True,
            },
            "hotels.com": {
                "wait_selector": "div[data-stid='lodging-card-responsive']",
                "wait_time": 10,
                "content_selectors": ["div[data-stid='lodging-card-responsive']"],
                "extract_names": True,
            },
            "marriott.com": {
                "wait_selector": "div.property-card",
                "wait_time": 10,
                "content_selectors": ["div.property-card", "h3.property-title"],
                "extract_names": True,
            },
            "hilton.com": {
                "wait_selector": "div.hotel-result",
                "wait_time": 10,
                "content_selectors": ["div.hotel-result", "h3.hotel-name"],
                "extract_names": True,
            },
            "fandango.com": {
                "wait_selector": "div.movie-card",
                "wait_time": 8,
                "content_selectors": ["div.movie-card", "h3.movie-title"],
                "extract_names": True,
            },
            "imdb.com": {
                "wait_selector": "div.ipc-metadata-list",
                "wait_time": 8,
                "content_selectors": ["div.ipc-metadata-list", "h3.ipc-title"],
                "extract_names": True,
            },
            "bbc.com": {
                "wait_selector": "div[data-testid='weather-temperature-celsius']",
                "wait_time": 10,
                "content_selectors": [
                    "div[data-testid='weather-temperature-celsius']",
                    "div.wr-day-summary",
                    "li.wr-day",
                    "div[class*='weather']",
                    "main",
                ],
                "extract_names": False,
            },
            "bbc.co.uk": {
                "wait_selector": "div[data-testid='weather-temperature-celsius']",
                "wait_time": 10,
                "content_selectors": [
                    "div[data-testid='weather-temperature-celsius']",
                    "div.wr-day-summary",
                    "li.wr-day",
                    "div[class*='weather']",
                    "main",
                ],
                "extract_names": False,
            },
            "weather-atlas.com": {
                "wait_selector": "div.weather-today",
                "wait_time": 10,
                "content_selectors": [
                    "div.weather-today",
                    "div.widget-weather",
                    "div#today",
                    "div.current-weather",
                    "table.weather-table",
                    "main",
                    "article",
                ],
                "extract_names": False,
            },
            "meteum.ai": {
                "wait_selector": "div[class*='weather']",
                "wait_time": 10,
                "content_selectors": [
                    "div[class*='weather']",
                    "main",
                ],
                "extract_names": False,
            },
            "theweathernetwork.com": {
                "wait_selector": "div[class*='forecast']",
                "wait_time": 10,
                "content_selectors": [
                    "div[class*='forecast']",
                    "div[class*='hourly']",
                    "main",
                ],
                "extract_names": False,
            },
        }

        # API-based site handlers
        self.api_sites: Dict[str, Any] = {
            "github.com": self._scrape_github
        }

    # ------------------------------------------------------------------
    # Public scraping helpers
    # ------------------------------------------------------------------

    def _scrape_urls(self, urls: List[str], use_async: bool = True) -> List[Dict[str, Any]]:
        """Scrape a list of URLs, optionally in parallel."""
        if use_async and len(urls) > 1:
            return self._scrape_urls_async(urls)
        return self._scrape_urls_sync(urls)

    def _scrape_urls_sync(self, urls: List[str]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for url in urls:
            results.append(self._scrape_single_url(url))
        return results

    def _scrape_urls_async(self, urls: List[str]) -> List[Dict[str, Any]]:
        result_map: Dict[str, Dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_url = {executor.submit(self._scrape_single_url, url): url for url in urls}
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    result_map[url] = future.result()
                except Exception as exc:
                    logger.error(f"Async scrape error for {url}: {exc}")
                    result_map[url] = self._error_result(url, str(exc))

        # Preserve original ordering
        return [result_map.get(url, self._error_result(url, "Missing result")) for url in urls]

    def _scrape_single_url(self, url: str) -> Dict[str, Any]:
        try:
            logger.info(f"Scraping: {url}")
            scraped = self._scrape_dispatcher(url)
            return {"url": url, "success": True, **scraped}
        except Exception as exc:
            logger.error(f"Error scraping {url}: {exc}")
            return self._error_result(url, str(exc))

    # ------------------------------------------------------------------
    # Dispatcher
    # ------------------------------------------------------------------

    def _scrape_dispatcher(self, url: str) -> Dict[str, Any]:
        domain = self._extract_domain(url)

        for api_domain, method in self.api_sites.items():
            if api_domain in domain:
                return method(url)

        if self._is_js_heavy(domain):
            return self._scrape_js(url, domain)

        return self._scrape_static(url)

    # ------------------------------------------------------------------
    # Static scraping
    # ------------------------------------------------------------------

    def _scrape_static(self, url: str) -> Dict[str, Any]:
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        for tag in soup(["script", "style", "noscript", "nav", "footer", "header"]):
            tag.decompose()

        title: str = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        elif soup.find("h1"):
            h1 = soup.find("h1")
            if h1:
                title = h1.get_text(strip=True)

        text_parts: List[str] = []
        # Use select() for CSS selectors, find_all() only for plain tag names
        for element in soup.select("p, article, section, main, div.content, div.article-body"):
            chunk = element.get_text(strip=True)
            if len(chunk) > 50:
                text_parts.append(chunk)

        text = " ".join(text_parts)[: self.max_chars]

        links: List[str] = []
        for a in soup.find_all("a", href=True):
            href: str = a["href"]
            full_url = urljoin(url, href)
            if full_url.startswith("http") and full_url not in links:
                links.append(full_url)

        return {"title": title, "text": text, "links": links[:50]}

    # ------------------------------------------------------------------
    # JS-heavy scraping via Selenium
    # ------------------------------------------------------------------

    def _scrape_js(self, url: str, domain: str) -> Dict[str, Any]:
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--window-size=1920,1080")
        options.add_argument(f"user-agent={self.session.headers['User-Agent']}")

        prefs: Dict[str, int] = {"profile.managed_default_content_settings.images": 2}
        options.add_experimental_option("prefs", prefs)
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        driver: Optional[webdriver.Chrome] = None
        try:
            driver = webdriver.Chrome(options=options)
            driver.set_page_load_timeout(self.timeout)
            driver.get(url)

            site_config = self._get_site_config(domain)
            wait_selector: Optional[str] = site_config.get("wait_selector")
            wait_time: int = site_config.get("wait_time", 10)
            content_selectors: List[str] = site_config.get("content_selectors", [])
            extract_names: bool = site_config.get("extract_names", False)

            if wait_selector:
                try:
                    WebDriverWait(driver, wait_time).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, wait_selector))
                    )
                    logger.info(f"Found selector: {wait_selector}")
                except TimeoutException:
                    logger.warning(f"Timeout waiting for selector: {wait_selector}")

            # Scroll to trigger lazy-loaded content
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight/3);")
            time.sleep(1.5)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
            time.sleep(1.5)

            html: str = driver.page_source
            soup = BeautifulSoup(html, "lxml")

            for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "iframe"]):
                tag.decompose()

            title = ""
            if soup.title and soup.title.string:
                title = soup.title.string.strip()
            elif soup.find("h1"):
                h1 = soup.find("h1")
                if h1:
                    title = h1.get_text(strip=True)

            text_elements: List[str] = []
            items_found: List[str] = []

            if content_selectors:
                for selector in content_selectors:
                    elements = soup.select(selector)
                    if elements:
                        logger.info(f"Found {len(elements)} elements with selector: {selector}")
                        for elem in elements[:30]:
                            chunk = elem.get_text(strip=True, separator=" ")
                            if len(chunk) > 30:
                                text_elements.append(chunk)
                                if extract_names:
                                    for tag in elem.find_all(["h2", "h3", "h4", "a"], limit=3):
                                        item_name = tag.get_text(strip=True)
                                        if 20 < len(item_name) < 200 and item_name not in items_found:
                                            items_found.append(item_name)

            if not text_elements:
                logger.info("Using fallback extraction")
                fallback_selectors = [
                    "main", "article", "[role='main']",
                    "div.content", "div.listing", "div.results",
                ]
                for selector in fallback_selectors:
                    for elem in soup.select(selector)[:20]:
                        chunk = elem.get_text(strip=True, separator=" ")
                        if len(chunk) > 50:
                            text_elements.append(chunk)

            if not text_elements:
                for p in soup.find_all("p"):
                    chunk = p.get_text(strip=True)
                    if len(chunk) > 50:
                        text_elements.append(chunk)

            combined = (
                " | ".join(items_found[:15]) if items_found else " ".join(text_elements)
            )
            text = combined[: self.max_chars]

            links: List[str] = []
            for a in soup.find_all("a", href=True):
                href: str = a["href"]
                if href.startswith("http") and href not in links:
                    links.append(href)
                elif href.startswith("/"):
                    full = urljoin(url, href)
                    if full not in links:
                        links.append(full)

            return {
                "title": title,
                "text": text or "Content loaded but no text extracted. Try adjusting selectors.",
                "links": links[:50],
                "items_count": len(items_found) if items_found else len(text_elements),
            }

        except WebDriverException as exc:
            raise RuntimeError(f"Browser automation failed: {exc}") from exc
        finally:
            if driver:
                driver.quit()

    # ------------------------------------------------------------------
    # GitHub API scraping
    # ------------------------------------------------------------------

    def _scrape_github(self, url: str) -> Dict[str, Any]:
        username: str = url.strip("/").split("/")[-1]
        api_url = f"{GITHUB_API_BASE}{username}/repos"

        resp = self.session.get(api_url, timeout=self.timeout)
        resp.raise_for_status()
        repos: List[Dict[str, Any]] = resp.json()

        repo_names: List[str] = [repo["name"] for repo in repos[:50]]
        repo_urls: List[str] = [repo["html_url"] for repo in repos[:50]]

        text = f"GitHub user {username} has {len(repos)} repositories: " + ", ".join(repo_names)

        return {
            "title": f"GitHub Profile: {username}",
            "text": text[: self.max_chars],
            "links": repo_urls,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_domain(self, url: str) -> str:
        return urlparse(url).netloc.lower()

    def _is_js_heavy(self, domain: str) -> bool:
        return any(site in domain for site in self.js_heavy_sites)

    def _get_site_config(self, domain: str) -> Dict[str, Any]:
        for site, config in self.js_heavy_sites.items():
            if site in domain:
                return config
        return {
            "wait_selector": None,
            "wait_time": 5,
            "content_selectors": [],
            "extract_names": False,
        }

    @staticmethod
    def _error_result(url: str, message: str) -> Dict[str, Any]:
        return {
            "url": url,
            "success": False,
            "title": "",
            "text": f"Error: {message}",
            "links": [],
        }


# ------------------------------------------------------------------
# Quick smoke-test (run directly: python web_scrape_tool.py)
# ------------------------------------------------------------------
if __name__ == "__main__":
    import asyncio

    async def main() -> None:
        tool = WebScrapeTool(max_chars=5000, max_workers=5)

        inputs: Dict[str, Any] = {
            "base_links": [
                "https://www.airbnb.com/s/Kathmandu--Nepal/homes",
                "https://www.booking.com/searchresults.html?ss=Kathmandu",
                "https://github.com/torvalds",
                (
                    "https://www.tripadvisor.com/Hotels-g293890"
                    "-Kathmandu_Kathmandu_Valley_Bagmati_Zone_Central_Region-Hotels.html"
                ),
            ],
            "max_results": 10,
        }

        result = await tool.execute(inputs)

        print(f"\nSuccess : {result.success}")
        if result.error:
            print(f"Error   : {result.error}")
        else:
            data = result.data
            print(f"Total   : {data['total_results']}")
            print(f"Time    : {data['search_time_ms']} ms")
            for item in data["results"]:
                print(f"\n  URL    : {item['url']}")
                print(f"  OK     : {item['success']}")
                print(f"  Title  : {item.get('title', '')[:80]}")
                print(f"  Text   : {item.get('text', '')[:200]}")

    asyncio.run(main())