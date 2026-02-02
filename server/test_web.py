from app.tools.web import search,scrape
from app.features.search_web.fetch_web_result import fetch_web_results_with_selenium,fetch_bing_results_with_selenium
import asyncio
import json

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

async def main ():
  # # fetch web results with selenium
  web_search_tool = search.WebSearchTool()
  result = await web_search_tool.execute({"query": "what is the current weather of janakpur", "max_results": 4})
  print(json.dumps(result.data, indent=2))

  urls_core = result.data.get("results", [])
  urls = [item['url'] for item in urls_core]
  print("Extracted URLs:", urls)

  # web_scrape
  web_scraper = scrape.WebScraper(max_chars=5000)
  result = web_scraper.scrape_urls(urls)
  print(json.dumps(result, indent=2))

if __name__ == "__main__":
  asyncio.run(main()) 
 