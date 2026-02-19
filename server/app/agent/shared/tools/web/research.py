from typing import Any, Dict, List
import asyncio
import json

from app.agent.shared.tools.base import BaseTool, ToolOutput
from app.agent.shared.tools.web.search import WebSearchTool
from app.agent.shared.tools.web.scrape import WebScrapeTool
from app.agent.shared.tools.ai.summarize import AiSummarizeTool

class WebResearchTool(BaseTool):
    """
    Orchestrates Web Search -> Web Scrape -> AI Summarize in a single flow.
    """
    def get_tool_name(self) -> str:
        return "web_research"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        query = self.get_input(inputs, "query")
        max_results = int(self.get_input(inputs, "max_results", 3))
        max_chars = int(self.get_input(inputs, "max_chars", 5000))
        
        # Execution context (injected by ExecutionEngine, None in manual testing)
        user_id = inputs.get("_user_id")
        print(f"User ID: | {self.get_tool_name()} | {user_id}")

        if not query:
            return ToolOutput(success=False, data={}, error="Query is required")

        # 1. Search
        search_tool = WebSearchTool()
        search_result = await search_tool.execute({"query": query, "max_results": max_results})
        
        if not search_result.success:
            return ToolOutput(success=False, data={}, error=f"Search failed: {search_result.error}")

        urls_data = search_result.data.get("results", [])
        if not urls_data:
             return ToolOutput(success=True, data={"summary": "No results found.", "detailed_content": "", "sources": []}, error=None)

        urls = [item['url'] for item in urls_data]
        
        # 2. Scrape
        scrape_tool = WebScrapeTool(max_chars=max_chars)
        scrape_result = await scrape_tool._execute({"base_links": urls, "max_results": max_results}) # Direct _execute to avoid double wrapping if needed, or public execute
        
        scraped_items = scrape_result.data.get("results", [])
        
        # Aggregate content
        concatenated_content = ""
        valid_sources = []
        
        for item in scraped_items:
            if item.get("success") and item.get("text"):
                text = item.get("text", "")
                concatenated_content += f"Source: {item.get('url')}\nTitle: {item.get('title')}\nContent:\n{text}\n\n{'='*50}\n\n"
                valid_sources.append({
                    "url": item.get('url'),
                    "title": item.get('title'),
                    "search_metadata": next((u for u in urls_data if u['url'] == item.get('url')), {})
                })

        if not concatenated_content:
             return ToolOutput(success=True, data={"summary": "Could not scrape any content from the search results.", "detailed_content": "", "sources": valid_sources}, error=None)

        # 3. Summarize
        summarize_tool = AiSummarizeTool()
        summary_result = await summarize_tool.execute({"context": concatenated_content, "query": query})

        if not summary_result.success:
             return ToolOutput(success=False, data={}, error=f"Summarization failed: {summary_result.error}")

        summary_data = summary_result.data
        summary_text = summary_data.get("summary", "")

        # 4. Stream TTS to the requesting client
        if user_id:
            try:
                from app.socket.utils import stream_tts_to_client
                await stream_tts_to_client(text=summary_text, user_id=user_id)
            except ImportError:
                # Socket module not available — standalone testing
                print(f"\n🔊 [TTS would say]: {summary_text}\n")

        return ToolOutput(
            success=True,
            data={
                "summary": summary_text,
                "detailed_content": summary_data.get("formatted_content"),
                "sources": valid_sources
            }
        )
