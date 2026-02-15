import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from typing import List, Dict, Optional
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

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# API Configuration
GITHUB_API_BASE = "https://api.github.com/users/"

class WebScraper:
    """
    Handles multiple website types including hotels, cinemas, social media, etc.
    """
    
    def __init__(self, max_chars: int = 5000, timeout: int = 20, max_workers: int = 5):
        """
        Initialize the scraper.
        
        Args:
            max_chars: Maximum characters to extract from text content
            timeout: Timeout in seconds for page loads
            max_workers: Maximum parallel workers for async scraping
        """
        self.max_chars = max_chars
        self.timeout = timeout
        self.max_workers = max_workers
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        
        # Enhanced site-specific configurations with better selectors
        self.js_heavy_sites = {
            "airbnb.com": {
                "wait_selector": "div[itemprop='itemListElement']",
                "wait_time": 12,
                "content_selectors": [
                    "div[itemprop='itemListElement']",
                    "div[data-testid='listing-card-title']",
                    "div.c4mnd7m"
                ],
                "extract_names": True
            },
            "booking.com": {
                "wait_selector": "div[data-testid='property-card']",
                "wait_time": 12,
                "content_selectors": [
                    "div[data-testid='property-card']",
                    "div[data-testid='title']",
                    "h3.a7ba9e5476",
                    "div[data-testid='price-and-discounted-price']"
                ],
                "extract_names": True
            },
            "instagram.com": {
                "wait_selector": "article",
                "wait_time": 8,
                "content_selectors": ["article"],
                "extract_names": False
            },
            "twitter.com": {
                "wait_selector": "article[data-testid='tweet']",
                "wait_time": 8,
                "content_selectors": ["article[data-testid='tweet']"],
                "extract_names": False
            },
            "x.com": {
                "wait_selector": "article[data-testid='tweet']",
                "wait_time": 8,
                "content_selectors": ["article[data-testid='tweet']"],
                "extract_names": False
            },
            "linkedin.com": {
                "wait_selector": "div.feed-shared-update-v2",
                "wait_time": 8,
                "content_selectors": ["div.feed-shared-update-v2"],
                "extract_names": False
            },
            "tripadvisor.com": {
                "wait_selector": "div.listing_title",
                "wait_time": 12,
                "content_selectors": [
                    "div.listing_title",
                    "div.prw_rup.prw_meta_hsx_responsive_listing",
                    "a.property_title",
                    "div.ui_column.is-9"
                ],
                "extract_names": True
            },
            "expedia.com": {
                "wait_selector": "div[data-stid='lodging-card-responsive']",
                "wait_time": 10,
                "content_selectors": ["div[data-stid='lodging-card-responsive']"],
                "extract_names": True
            },
            "hotels.com": {
                "wait_selector": "div[data-stid='lodging-card-responsive']",
                "wait_time": 10,
                "content_selectors": ["div[data-stid='lodging-card-responsive']"],
                "extract_names": True
            },
            "marriott.com": {
                "wait_selector": "div.property-card",
                "wait_time": 10,
                "content_selectors": ["div.property-card", "h3.property-title"],
                "extract_names": True
            },
            "hilton.com": {
                "wait_selector": "div.hotel-result",
                "wait_time": 10,
                "content_selectors": ["div.hotel-result", "h3.hotel-name"],
                "extract_names": True
            },
            "fandango.com": {
                "wait_selector": "div.movie-card",
                "wait_time": 8,
                "content_selectors": ["div.movie-card", "h3.movie-title"],
                "extract_names": True
            },
            "imdb.com": {
                "wait_selector": "div.ipc-metadata-list",
                "wait_time": 8,
                "content_selectors": ["div.ipc-metadata-list", "h3.ipc-title"],
                "extract_names": True
            },
        }
        
        # API-based sites
        self.api_sites = {
            "github.com": self._scrape_github
        }

    # ---------------------
    # Public methods
    # ---------------------
    def scrape_urls(self, urls: List[str], use_async: bool = True) -> List[Dict]:
        """
        Scrape multiple URLs. Use async for faster processing.
        
        Args:
            urls: List of URLs to scrape
            use_async: Whether to use parallel processing (recommended)
            
        Returns:
            List of dictionaries containing scraped data
        """
        if use_async and len(urls) > 1:
            return self._scrape_urls_async(urls)
        else:
            return self._scrape_urls_sync(urls)
    
    def _scrape_urls_sync(self, urls: List[str]) -> List[Dict]:
        """Synchronous scraping (one by one)."""
        results = []
        for url in urls:
            try:
                logger.info(f"Scraping: {url}")
                result = self._scrape_dispatcher(url)
                results.append({"url": url, "success": True, **result})
            except Exception as e:
                logger.error(f"Error scraping {url}: {str(e)}")
                results.append({
                    "url": url,
                    "success": False,
                    "title": "",
                    "text": f"Error: {str(e)}",
                    "links": []
                })
        return results
    
    def _scrape_urls_async(self, urls: List[str]) -> List[Dict]:
        """Asynchronous scraping (parallel processing)."""
        results = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_url = {executor.submit(self._scrape_single_url, url): url for url in urls}
            
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    logger.error(f"Error in async scraping {url}: {str(e)}")
                    results.append({
                        "url": url,
                        "success": False,
                        "title": "",
                        "text": f"Error: {str(e)}",
                        "links": []
                    })
        
        # Sort results to match input order
        url_to_result = {r['url']: r for r in results}
        return [url_to_result.get(url, {"url": url, "success": False, "text": "Missing result"}) for url in urls]
    
    def _scrape_single_url(self, url: str) -> Dict:
        """Scrape a single URL (for async execution)."""
        try:
            logger.info(f"Scraping: {url}")
            result = self._scrape_dispatcher(url)
            return {"url": url, "success": True, **result}
        except Exception as e:
            logger.error(f"Error scraping {url}: {str(e)}")
            return {
                "url": url,
                "success": False,
                "title": "",
                "text": f"Error: {str(e)}",
                "links": []
            }

    # ---------------------
    # Dispatcher
    # ---------------------
    def _scrape_dispatcher(self, url: str) -> Dict:
        """
        Route URL to appropriate scraping method.
        
        Args:
            url: URL to scrape
            
        Returns:
            Dictionary containing scraped data
        """
        domain = self._extract_domain(url)
        
        # Check if API method exists
        for api_domain, method in self.api_sites.items():
            if api_domain in domain:
                return method(url)
        
        # Check if JS-heavy site
        if self._is_js_heavy(domain):
            return self._scrape_js(url, domain)
        
        # Default to static scraping
        return self._scrape_static(url)

    # ---------------------
    # Static scraping
    # ---------------------
    def _scrape_static(self, url: str) -> Dict:
        """
        Scrape static HTML content.
        
        Args:
            url: URL to scrape
            
        Returns:
            Dictionary with title, text, and links
        """
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Remove unwanted elements
        for tag in soup(["script", "style", "noscript", "nav", "footer", "header"]):
            tag.decompose()

        # Extract title
        title = ""
        if soup.title:
            title = soup.title.string.strip()
        elif soup.find("h1"):
            title = soup.find("h1").get_text(strip=True)

        # Extract text from various elements
        text_elements = []
        for tag in soup.find_all(["p", "article", "section", "div.content", "main"]):
            text = tag.get_text(strip=True)
            if len(text) > 50:  # Filter out short snippets
                text_elements.append(text)
        
        text = " ".join(text_elements)[:self.max_chars]

        # Extract links
        links = []
        for a in soup.find_all("a", href=True):
            href = a.get("href")
            full_url = urljoin(url, href)
            if full_url.startswith("http") and full_url not in links:
                links.append(full_url)

        return {
            "title": title,
            "text": text,
            "links": links[:50]
        }

    # ---------------------
    # JS-heavy scraping via Selenium
    # ---------------------
    def _scrape_js(self, url: str, domain: str) -> Dict:
        """
        Scrape JavaScript-heavy sites using Selenium with enhanced extraction.
        
        Args:
            url: URL to scrape
            domain: Domain name for site-specific handling
            
        Returns:
            Dictionary with title, text, and links
        """
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--window-size=1920,1080")
        options.add_argument(f"user-agent={self.session.headers['User-Agent']}")
        
        # Disable images for faster loading
        prefs = {"profile.managed_default_content_settings.images": 2}
        options.add_experimental_option("prefs", prefs)
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)

        driver = None
        try:
            driver = webdriver.Chrome(options=options)
            driver.set_page_load_timeout(self.timeout)
            driver.get(url)
            
            # Site-specific wait configuration
            site_config = self._get_site_config(domain)
            wait_selector = site_config.get("wait_selector")
            wait_time = site_config.get("wait_time", 10)
            content_selectors = site_config.get("content_selectors", [])
            extract_names = site_config.get("extract_names", False)
            
            if wait_selector:
                try:
                    # Wait for specific element
                    WebDriverWait(driver, wait_time).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, wait_selector))
                    )
                    logger.info(f"Found selector: {wait_selector}")
                except TimeoutException:
                    logger.warning(f"Timeout waiting for selector: {wait_selector}")
            
            # Scroll to trigger lazy loading
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight/3);")
            time.sleep(1.5)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
            time.sleep(1.5)
            
            # Get page source
            html = driver.page_source
            soup = BeautifulSoup(html, "lxml")
            
            # Remove unwanted elements
            for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "iframe"]):
                tag.decompose()

            # Extract title
            title = ""
            if soup.title:
                title = soup.title.string.strip() if soup.title.string else ""
            elif soup.find("h1"):
                title = soup.find("h1").get_text(strip=True)

            # Enhanced text extraction with site-specific selectors
            text_elements = []
            items_found = []
            
            # Try site-specific selectors first
            if content_selectors:
                for selector in content_selectors:
                    elements = soup.select(selector)
                    if elements:
                        logger.info(f"Found {len(elements)} elements with selector: {selector}")
                        for elem in elements[:30]:  # Limit to first 30 elements
                            text = elem.get_text(strip=True, separator=" ")
                            if len(text) > 30:
                                text_elements.append(text)
                                
                                # Extract names/titles if enabled
                                if extract_names:
                                    # Try to find hotel/property names in the element
                                    for tag in elem.find_all(["h2", "h3", "h4", "a"], limit=3):
                                        item_name = tag.get_text(strip=True)
                                        if 20 < len(item_name) < 200 and item_name not in items_found:
                                            items_found.append(item_name)
            
            # Fallback to general content extraction
            if not text_elements:
                logger.info("Using fallback extraction")
                general_selectors = [
                    "main", "article", "[role='main']", 
                    "div.content", "div.listing", "div.results"
                ]
                
                for selector in general_selectors:
                    elements = soup.select(selector)
                    if elements:
                        for elem in elements[:20]:
                            text = elem.get_text(strip=True, separator=" ")
                            if len(text) > 50:
                                text_elements.append(text)
            
            # Final fallback to paragraphs
            if not text_elements:
                for p in soup.find_all("p"):
                    text = p.get_text(strip=True)
                    if len(text) > 50:
                        text_elements.append(text)
            
            # Combine extracted text
            combined_text = " | ".join(items_found[:15]) if items_found else " ".join(text_elements)
            text = combined_text[:self.max_chars]

            # Extract links
            links = []
            for a in soup.find_all("a", href=True):
                href = a.get("href")
                if href.startswith("http") and href not in links:
                    links.append(href)
                elif href.startswith("/"):
                    full_url = urljoin(url, href)
                    if full_url not in links:
                        links.append(full_url)

            return {
                "title": title,
                "text": text if text else "Content loaded but no text extracted. Try adjusting selectors.",
                "links": links[:50],
                "items_count": len(items_found) if items_found else len(text_elements)
            }
            
        except WebDriverException as e:
            logger.error(f"Selenium error: {str(e)}")
            raise Exception(f"Browser automation failed: {str(e)}")
        finally:
            if driver:
                driver.quit()

    # ---------------------
    # GitHub API scraping
    # ---------------------
    def _scrape_github(self, url: str) -> Dict:
        """
        Scrape GitHub user repositories using API.
        
        Args:
            url: GitHub profile URL
            
        Returns:
            Dictionary with repos information
        """
        username = url.strip("/").split("/")[-1]
        api_url = f"{GITHUB_API_BASE}{username}/repos"
        
        resp = self.session.get(api_url, timeout=self.timeout)
        resp.raise_for_status()
        repos = resp.json()
        
        repo_names = [repo["name"] for repo in repos[:50]]
        repo_urls = [repo["html_url"] for repo in repos[:50]]
        
        text = f"GitHub user {username} has {len(repos)} repositories: " + ", ".join(repo_names)
        
        return {
            "title": f"GitHub Profile: {username}",
            "text": text[:self.max_chars],
            "links": repo_urls
        }

    # ---------------------
    # Helper methods
    # ---------------------
    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        parsed = urlparse(url)
        return parsed.netloc.lower()
    
    def _is_js_heavy(self, domain: str) -> bool:
        """Check if domain requires JavaScript rendering."""
        return any(site in domain for site in self.js_heavy_sites.keys())
    
    def _get_site_config(self, domain: str) -> Dict:
        """Get site-specific configuration."""
        for site, config in self.js_heavy_sites.items():
            if site in domain:
                return config
        return {
            "wait_selector": None, 
            "wait_time": 5, 
            "content_selectors": [],
            "extract_names": False
        }


# ---------------------
# Usage Example
# ---------------------
if __name__ == "__main__":
    scraper = WebScraper(max_chars=5000, max_workers=5)
    
    test_urls = [
        "https://www.airbnb.com/s/Kathmandu--Nepal/homes",
        "https://www.booking.com/searchresults.html?ss=Kathmandu",
        "https://github.com/torvalds",
        "https://www.tripadvisor.com/Hotels-g293890-Kathmandu_Kathmandu_Valley_Bagmati_Zone_Central_Region-Hotels.html",
    ]
    
    # Async scraping (FAST - parallel execution)
    print("\n" + "="*80)
    print("ASYNC SCRAPING (Parallel - Recommended)")
    print("="*80)
    import time as time_module
    start = time_module.time()
    results = scraper.scrape_urls(test_urls, use_async=True)
    async_time = time_module.time() - start
    
    for result in results:
        print(f"\n{'='*80}")
        print(f"URL: {result['url']}")
        print(f"Success: {result['success']}")
        print(f"Title: {result['title'][:100]}...")
        print(f"Text Preview: {result['text'][:300]}...")
        print(f"Links Found: {len(result['links'])}")
        if 'items_count' in result:
            print(f"Items Extracted: {result['items_count']}")
    
    print(f"\n{'='*80}")
    print(f"ASYNC TIME: {async_time:.2f} seconds")
    print("="*80)
    
    # Sync scraping (SLOW - one by one)
    print("\n\nSYNC SCRAPING (Sequential - Slower)")
    print("="*80)
    start = time_module.time()
    results_sync = scraper.scrape_urls(test_urls, use_async=False)
    sync_time = time_module.time() - start
    print(f"SYNC TIME: {sync_time:.2f} seconds")
    print(f"SPEEDUP: {sync_time/async_time:.2f}x faster with async!")
    print("="*80)