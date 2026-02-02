# app/tools/web/search.py
"""
Web Search Tool

Matches tool_registry.json:
{
  "tool_name": "web_search",
  "params_schema": {
    "query": {"type": "string", "required": true},
    "max_results": {"type": "integer", "required": false, "default": 10}
  },
  "output_schema": {
    "success": {"type": "boolean"},
    "data": {
      "results": {"type": "array"},
      "total_results": {"type": "integer"},
      "search_time_ms": {"type": "number"}
    }
  }
}
"""


import asyncio
from typing import Dict, Any
from datetime import datetime

from app.tools.base import BaseTool, ToolOutput

# web searcher duckduckgo
from ddgs import DDGS
import re

BLOCKED_DOMAINS = (
    "baidu.com",
    "zhihu.com",
    "weibo.com",
    "csdn.net"
)


class WebSearchTool(BaseTool):
    """
    Web search tool
    
    Can run on: SERVER (typically)
    
    In production: Integrate with:
    - SerpAPI
    - Brave Search API
    - Google Custom Search
    - Bing Search API
    
    For now: Returns mock data
    """
    
    def get_tool_name(self) -> str:
        return "web_search"
    
    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """
        Execute web search
        
        Inputs:
            query: str - Search query
            max_results: int - Max number of results (default: 10)
        
        Returns:
            ToolOutput with search results
        """
        # Extract inputs
        query = inputs.get("query", "")
        print("inputs: inside search.py", inputs)
        max_results = inputs.get("max_results", 10)
        
        if not query:
            return ToolOutput(
                success=False,
                data={},
                error="Query is required"
            )
        
        self.logger.info(f"Searching: '{query}' (max: {max_results})")
        
        # Simulate search delay
        await asyncio.sleep(0.5)
        
        # Run search
        init_time = datetime.now()
        results = await self._fetch_web_results(query, max_results)
        search_time_ms = (datetime.now() - init_time).total_seconds() * 1000    
        return ToolOutput(
            success=True,
            data={
                "query_demo": query,
                "results": results,
                "total_results": len(results),
                "search_time_ms": search_time_ms
            },
            error=None
        )

    def _looks_english(self ,text: str) -> bool:
        # Reject if contains CJK characters
        return not re.search(r"[\u4e00-\u9fff]", text)

    async def _fetch_web_results(self, query: str, limit: int = 5):
        results = []

        with DDGS() as ddgs:
            for r in ddgs.text(
                query,
                max_results=limit * 3,   # fetch extra, filter later
                region="us-en",
                safesearch="low"
            ):
                title = r.get("title", "")
                snippet = r.get("body", "")
                url = r.get("href", "")

                if not url.startswith("http"):
                    continue

                if any(d in url for d in BLOCKED_DOMAINS):
                    continue

                if not self._looks_english(title + snippet):
                    continue

                results.append({
                    "title": title,
                    "url": url,
                    "snippet": snippet
                })

                if len(results) >= limit:
                    break

        return results

# testing 
    def _mock_search(self, query: str, max_results: int) -> list[Dict[str, Any]]:
        """
        Mock search results
        
        In production: Replace with actual API call
        """
        # Simulate different results based on query
        if "gold" in query.lower() or "price" in query.lower():
            results = [
                {
                    "title": f"Gold Price Today - {datetime.now().strftime('%B %d, %Y')}",
                    "url": "https://goldprice.org/today",
                    "snippet": "Current gold price is $2,050 per ounce, up 0.5% from yesterday.",
                    "price": "$2,050",
                    "source": "GoldPrice.org"
                },
                {
                    "title": "Live Gold Prices - Kitco",
                    "url": "https://kitco.com/gold",
                    "snippet": "Real-time gold pricing and market analysis",
                    "price": "$2,048",
                    "source": "Kitco"
                }
            ]
        elif "news" in query.lower() or "tech" in query.lower():
            results = [
                {
                    "title": "Latest Tech News - TechCrunch",
                    "url": "https://techcrunch.com",
                    "snippet": "Breaking technology news and analysis",
                    "source": "TechCrunch"
                },
                {
                    "title": "Tech Industry Updates",
                    "url": "https://theverge.com",
                    "snippet": "The latest in technology and innovation",
                    "source": "The Verge"
                }
            ]
        else:
            results = [
                {
                    "title": f"Search results for: {query}",
                    "url": f"https://example.com/search?q={query}",
                    "snippet": f"Information about {query}",
                    "source": "Example.com"
                }
            ]
        
        return results[:max_results]
    
    def _format_results(self, query: str, results: list) -> str:
        """Format results as human-readable text"""
        lines = [
            f"Search Results for: '{query}'",
            "=" * 60,
            ""
        ]
        
        for i, result in enumerate(results, 1):
            lines.append(f"{i}. {result['title']}")
            lines.append(f"   URL: {result['url']}")
            lines.append(f"   {result['snippet']}")
            
            if "price" in result:
                lines.append(f"   Price: {result['price']}")
            
            lines.append("")
        
        lines.append(f"Total results: {len(results)}")
        lines.append(f"Searched at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        return "\n".join(lines)

    