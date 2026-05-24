"""
Notion Tools — Search pages, read content, create pages, query databases

Requires OAuth connection via /auth/notion/connect
"""
import logging
from typing import Any, Dict, List, Optional
import httpx

from tools.base_tool import BaseTool, ToolMetadata, ToolParameter

logger = logging.getLogger(__name__)

NOTION_API_VERSION = "2022-06-28"


async def _get_notion_client(user_id: str) -> str:
    """Get valid Notion access token for user."""
    from app.features.external_service.token_manager import get_valid_access_token
    return await get_valid_access_token(user_id=user_id, service="notion")


class NotionSearchTool(BaseTool):
    """Search across all pages and databases in user's Notion workspace."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="notion_search",
            display_name="Search Notion",
            description="Search for pages and databases in Notion workspace by query text",
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search query text",
                    required=True,
                ),
                ToolParameter(
                    name="filter_type",
                    type="string",
                    description="Filter by type: 'page' or 'database' (optional)",
                    required=False,
                ),
            ],
            category="productivity",
            requires_approval=False,
        )

    async def _execute(self, query: str, filter_type: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        user_id = kwargs.get("user_id")
        if not user_id:
            return {"error": "user_id required for Notion operations"}

        try:
            token = await _get_notion_client(user_id)
            
            search_body: Dict[str, Any] = {"query": query}
            if filter_type:
                search_body["filter"] = {"property": "object", "value": filter_type}
            
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.notion.com/v1/search",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Notion-Version": NOTION_API_VERSION,
                        "Content-Type": "application/json",
                    },
                    json=search_body,
                    timeout=30.0,
                )
            
            if resp.status_code != 200:
                return {"error": f"Notion API error: {resp.status_code} - {resp.text}"}
            
            data = resp.json()
            results = []
            
            for item in data.get("results", []):
                result = {
                    "id": item.get("id"),
                    "type": item.get("object"),
                    "url": item.get("url"),
                }
                
                # Extract title based on type
                if item.get("object") == "page":
                    props = item.get("properties", {})
                    title_prop = props.get("title", {})
                    if title_prop.get("title"):
                        result["title"] = "".join([t.get("plain_text", "") for t in title_prop["title"]])
                elif item.get("object") == "database":
                    title = item.get("title", [])
                    if title:
                        result["title"] = "".join([t.get("plain_text", "") for t in title])
                
                results.append(result)
            
            return {
                "success": True,
                "results": results,
                "count": len(results),
            }
        
        except Exception as e:
            logger.error(f"Notion search failed: {e}")
            return {"error": str(e)}


class NotionReadPageTool(BaseTool):
    """Read content from a Notion page."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="notion_read_page",
            display_name="Read Notion Page",
            description="Read the content of a specific Notion page by ID",
            parameters=[
                ToolParameter(
                    name="page_id",
                    type="string",
                    description="Notion page ID (from search results or URL)",
                    required=True,
                ),
            ],
            category="productivity",
            requires_approval=False,
        )

    async def _execute(self, page_id: str, **kwargs) -> Dict[str, Any]:
        user_id = kwargs.get("user_id")
        if not user_id:
            return {"error": "user_id required for Notion operations"}

        try:
            token = await _get_notion_client(user_id)
            
            async with httpx.AsyncClient() as client:
                # Get page metadata
                page_resp = await client.get(
                    f"https://api.notion.com/v1/pages/{page_id}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Notion-Version": NOTION_API_VERSION,
                    },
                    timeout=30.0,
                )
                
                if page_resp.status_code != 200:
                    return {"error": f"Failed to fetch page: {page_resp.status_code}"}
                
                page_data = page_resp.json()
                
                # Get page blocks (content)
                blocks_resp = await client.get(
                    f"https://api.notion.com/v1/blocks/{page_id}/children",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Notion-Version": NOTION_API_VERSION,
                    },
                    timeout=30.0,
                )
                
                if blocks_resp.status_code != 200:
                    return {"error": f"Failed to fetch blocks: {blocks_resp.status_code}"}
                
                blocks_data = blocks_resp.json()
                
                # Extract text content from blocks
                content_parts = []
                for block in blocks_data.get("results", []):
                    block_type = block.get("type")
                    block_content = block.get(block_type, {})
                    
                    if "rich_text" in block_content:
                        text = "".join([t.get("plain_text", "") for t in block_content["rich_text"]])
                        if text:
                            content_parts.append(text)
                
                return {
                    "success": True,
                    "page_id": page_id,
                    "url": page_data.get("url"),
                    "content": "\n\n".join(content_parts),
                    "block_count": len(blocks_data.get("results", [])),
                }
        
        except Exception as e:
            logger.error(f"Notion read page failed: {e}")
            return {"error": str(e)}


class NotionCreatePageTool(BaseTool):
    """Create a new page in Notion."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="notion_create_page",
            display_name="Create Notion Page",
            description="Create a new page in Notion with title and content",
            parameters=[
                ToolParameter(
                    name="title",
                    type="string",
                    description="Page title",
                    required=True,
                ),
                ToolParameter(
                    name="content",
                    type="string",
                    description="Page content (plain text)",
                    required=True,
                ),
                ToolParameter(
                    name="parent_page_id",
                    type="string",
                    description="Parent page ID (optional, creates in workspace root if not provided)",
                    required=False,
                ),
            ],
            category="productivity",
            requires_approval=True,
        )

    async def _execute(self, title: str, content: str, parent_page_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        user_id = kwargs.get("user_id")
        if not user_id:
            return {"error": "user_id required for Notion operations"}

        try:
            token = await _get_notion_client(user_id)
            
            # Build parent reference
            parent: Dict[str, Any]
            if parent_page_id:
                parent = {"type": "page_id", "page_id": parent_page_id}
            else:
                # Need to get workspace - for now, require parent_page_id
                return {"error": "parent_page_id is required (workspace root creation not yet supported)"}
            
            # Build page payload
            page_data = {
                "parent": parent,
                "properties": {
                    "title": {
                        "title": [{"text": {"content": title}}]
                    }
                },
                "children": [
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"text": {"content": content}}]
                        }
                    }
                ]
            }
            
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.notion.com/v1/pages",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Notion-Version": NOTION_API_VERSION,
                        "Content-Type": "application/json",
                    },
                    json=page_data,
                    timeout=30.0,
                )
            
            if resp.status_code != 200:
                return {"error": f"Failed to create page: {resp.status_code} - {resp.text}"}
            
            result = resp.json()
            
            return {
                "success": True,
                "page_id": result.get("id"),
                "url": result.get("url"),
                "title": title,
            }
        
        except Exception as e:
            logger.error(f"Notion create page failed: {e}")
            return {"error": str(e)}
