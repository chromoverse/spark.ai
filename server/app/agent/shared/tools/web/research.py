from typing import Any, Dict, List
import asyncio
import json
import logging

from app.agent.shared.tools.base import BaseTool, ToolOutput
from app.agent.shared.tools.web.search import WebSearchTool
from app.agent.shared.tools.web.scrape import WebScrapeTool
from app.agent.shared.tools.ai.summarize import AiSummarizeTool

logger = logging.getLogger(__name__)

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

        # 4. Emit results to client (fire-and-forget — never blocks tool)
        if user_id:
            try:
                from app.socket.utils import fire_socket_event, fire_tts
                
                # Emit the research result data to client
                logger.info(f"📡 [WebResearch] Emitting result to user {user_id}")
                fire_socket_event(
                    "research-result",
                    {
                        "summary": summary_text,
                        "sources": [s.get("url") for s in valid_sources],
                        "query": query
                    },
                    user_id=user_id
                )
                
                # Also speak the summary via TTS
                if summary_text:
                    logger.info(f"🔊 [WebResearch] Firing TTS for user {user_id}: {summary_text[:50]}...")
                    fire_tts(text=summary_text, user_id=user_id)
                
            except ImportError:
                # Socket module not available — standalone testing
                print(f"\n🔊 [TTS would say]: {summary_text}\n")
            except Exception as e:
                logger.error(f"❌ [WebResearch] Emission failed: {e}", exc_info=True)

        return ToolOutput(
            success=True,
            data={
                "summary": summary_text,
                "detailed_content": summary_data.get("formatted_content"),
                "sources": valid_sources
            }
        )
