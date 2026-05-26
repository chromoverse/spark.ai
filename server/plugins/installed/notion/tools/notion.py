"""
Notion Tools — Search pages, read content, create pages, query databases.

Requires OAuth connection via /auth/notion/connect.
Notion access tokens are permanent (no refresh needed).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx

from app.plugins.tools.tool_base import BaseTool, ToolOutput

logger = logging.getLogger(__name__)

NOTION_API_VERSION = "2022-06-28"
NOTION_API_BASE = "https://api.notion.com/v1"


async def _get_token(user_id: str) -> str:
    """Return a valid Notion access token for the user."""
    from app.features.external_service.token_manager import get_valid_access_token
    try:
        return await get_valid_access_token(user_id=user_id, service="notion")
    except RuntimeError as e:
        # Token is invalid or revoked - provide clear reconnection message
        error_msg = str(e)
        if "No active" in error_msg or "Re-auth required" in error_msg or "revoked" in error_msg:
            raise RuntimeError(
                "Notion connection is no longer authorized. Please reconnect Notion in Settings > Connectors."
            ) from e
        raise


def _headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json",
    }


def _extract_title(item: dict) -> str:
    """Pull the human-readable title out of a Notion page or database object."""
    if item.get("object") == "page":
        props = item.get("properties", {})
        # Pages can store title in "title", "Name", or any title-type property
        for prop_val in props.values():
            if prop_val.get("type") == "title" and prop_val.get("title"):
                return "".join(t.get("plain_text", "") for t in prop_val["title"])
    elif item.get("object") == "database":
        title = item.get("title", [])
        if title:
            return "".join(t.get("plain_text", "") for t in title)
    return "(untitled)"


# ── Tools ─────────────────────────────────────────────────────────────────────

class NotionSearchTool(BaseTool):
    """Search across all pages and databases in the user's Notion workspace."""

    TOOL_DESCRIPTION = "Search for pages and databases in Notion workspace by query text"
    EXECUTION_TARGET = "server"
    TOOL_CATEGORY = "productivity"
    METADATA = {"summary_tts": True}
    PARAMS_SCHEMA = {
        "user_id": {"type": "string", "required": True},
        "query": {"type": "string", "required": True, "description": "Search query text"},
        "filter_type": {
            "type": "string",
            "required": False,
            "description": "Filter results by type: 'page' or 'database'",
        },
        "limit": {
            "type": "integer",
            "required": False,
            "default": 20,
            "description": "Max number of results to return",
        },
    }
    OUTPUT_SCHEMA = {
        "success": {"type": "boolean"},
        "data": {
            "results": {"type": "array"},
            "count": {"type": "integer"},
        },
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "search my Notion for project notes"}]
    SEMANTIC_TAGS = ["notion", "search", "pages", "database", "workspace"]

    def get_tool_name(self) -> str:
        return "notion_search"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        user_id = inputs.get("_user_id") or inputs.get("user_id")
        if not user_id:
            return ToolOutput(success=False, data={}, error="user_id required")

        query = str(inputs.get("query", "")).strip()
        filter_type: Optional[str] = inputs.get("filter_type")
        limit = int(inputs.get("limit", 20))

        try:
            token = await _get_token(user_id)

            body: Dict[str, Any] = {"query": query, "page_size": min(limit, 100)}
            if filter_type in ("page", "database"):
                body["filter"] = {"property": "object", "value": filter_type}

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{NOTION_API_BASE}/search",
                    headers=_headers(token),
                    json=body,
                    timeout=30.0,
                )

            if resp.status_code != 200:
                error_text = resp.text
                # Handle 401 unauthorized specifically
                if resp.status_code == 401:
                    return ToolOutput(
                        success=False, data={},
                        error="Notion connection is no longer authorized. Please reconnect Notion in Settings > Connectors.",
                    )
                return ToolOutput(
                    success=False, data={},
                    error=f"Notion API error {resp.status_code}: {error_text}",
                )

            data = resp.json()
            results = [
                {
                    "id": item.get("id"),
                    "type": item.get("object"),
                    "title": _extract_title(item),
                    "url": item.get("url"),
                }
                for item in data.get("results", [])
            ]

            return ToolOutput(
                success=True,
                data={"results": results, "count": len(results)},
            )

        except Exception as exc:
            logger.error("notion_search failed: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))


class NotionReadPageTool(BaseTool):
    """Read the full text content of a Notion page."""

    TOOL_DESCRIPTION = "Read the content of a specific Notion page by ID"
    EXECUTION_TARGET = "server"
    TOOL_CATEGORY = "productivity"
    PARAMS_SCHEMA = {
        "user_id": {"type": "string", "required": True},
        "page_id": {
            "type": "string",
            "required": True,
            "description": "Notion page ID (from search results or page URL)",
        },
    }
    OUTPUT_SCHEMA = {
        "success": {"type": "boolean"},
        "data": {
            "page_id": {"type": "string"},
            "url": {"type": "string"},
            "title": {"type": "string"},
            "content": {"type": "string"},
            "block_count": {"type": "integer"},
        },
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "read my Notion page about Q3 roadmap"}]
    SEMANTIC_TAGS = ["notion", "read", "page", "content"]

    def get_tool_name(self) -> str:
        return "notion_read_page"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        user_id = inputs.get("_user_id") or inputs.get("user_id")
        if not user_id:
            return ToolOutput(success=False, data={}, error="user_id required")

        page_id = str(inputs.get("page_id", "")).strip()
        if not page_id:
            return ToolOutput(success=False, data={}, error="page_id required")

        try:
            token = await _get_token(user_id)
            hdrs = _headers(token)

            async with httpx.AsyncClient() as client:
                page_resp, blocks_resp = await _parallel_get(
                    client, hdrs,
                    f"{NOTION_API_BASE}/pages/{page_id}",
                    f"{NOTION_API_BASE}/blocks/{page_id}/children",
                )

            if page_resp.status_code != 200:
                if page_resp.status_code == 401:
                    return ToolOutput(
                        success=False, data={},
                        error="Notion connection is no longer authorized. Please reconnect Notion in Settings > Connectors.",
                    )
                return ToolOutput(
                    success=False, data={},
                    error=f"Failed to fetch page: {page_resp.status_code}",
                )
            if blocks_resp.status_code != 200:
                if blocks_resp.status_code == 401:
                    return ToolOutput(
                        success=False, data={},
                        error="Notion connection is no longer authorized. Please reconnect Notion in Settings > Connectors.",
                    )
                return ToolOutput(
                    success=False, data={},
                    error=f"Failed to fetch page content: {blocks_resp.status_code}",
                )

            page_data = page_resp.json()
            blocks_data = blocks_resp.json()

            # Extract plain text from blocks
            content_parts: list[str] = []
            for block in blocks_data.get("results", []):
                block_type = block.get("type")
                block_content = block.get(block_type, {})
                if "rich_text" in block_content:
                    text = "".join(
                        t.get("plain_text", "") for t in block_content["rich_text"]
                    )
                    if text:
                        content_parts.append(text)

            return ToolOutput(
                success=True,
                data={
                    "page_id": page_id,
                    "url": page_data.get("url", ""),
                    "title": _extract_title(page_data),
                    "content": "\n\n".join(content_parts),
                    "block_count": len(blocks_data.get("results", [])),
                },
            )

        except Exception as exc:
            logger.error("notion_read_page failed: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))


async def _parallel_get(client: httpx.AsyncClient, headers: dict, *urls: str):
    """Fire multiple GET requests concurrently and return responses in order."""
    import asyncio
    tasks = [client.get(url, headers=headers, timeout=30.0) for url in urls]
    return await asyncio.gather(*tasks)


class NotionCreatePageTool(BaseTool):
    """Create a new page in Notion under a parent page."""

    TOOL_DESCRIPTION = "Create a new page in Notion with a title and text content"
    EXECUTION_TARGET = "server"
    TOOL_CATEGORY = "productivity"
    PARAMS_SCHEMA = {
        "user_id": {"type": "string", "required": True},
        "title": {"type": "string", "required": True, "description": "Page title"},
        "content": {
            "type": "string",
            "required": True,
            "description": "Page body text",
        },
        "parent_page_id": {
            "type": "string",
            "required": True,
            "description": "ID of the parent page to create this page under",
        },
    }
    OUTPUT_SCHEMA = {
        "success": {"type": "boolean"},
        "data": {
            "page_id": {"type": "string"},
            "url": {"type": "string"},
            "title": {"type": "string"},
        },
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "create a Notion page called Meeting Notes"}]
    SEMANTIC_TAGS = ["notion", "create", "page", "write"]

    def get_tool_name(self) -> str:
        return "notion_create_page"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        user_id = inputs.get("_user_id") or inputs.get("user_id")
        if not user_id:
            return ToolOutput(success=False, data={}, error="user_id required")

        title = str(inputs.get("title", "")).strip()
        content = str(inputs.get("content", "")).strip()
        parent_page_id = str(inputs.get("parent_page_id", "")).strip()

        if not title:
            return ToolOutput(success=False, data={}, error="title required")
        if not parent_page_id:
            return ToolOutput(success=False, data={}, error="parent_page_id required")

        try:
            token = await _get_token(user_id)

            payload = {
                "parent": {"type": "page_id", "page_id": parent_page_id},
                "properties": {
                    "title": {"title": [{"text": {"content": title}}]}
                },
                "children": [
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"text": {"content": content}}]
                        },
                    }
                ],
            }

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{NOTION_API_BASE}/pages",
                    headers=_headers(token),
                    json=payload,
                    timeout=30.0,
                )

            if resp.status_code not in (200, 201):
                if resp.status_code == 401:
                    return ToolOutput(
                        success=False, data={},
                        error="Notion connection is no longer authorized. Please reconnect Notion in Settings > Connectors.",
                    )
                return ToolOutput(
                    success=False, data={},
                    error=f"Failed to create page: {resp.status_code} — {resp.text}",
                )

            result = resp.json()
            return ToolOutput(
                success=True,
                data={
                    "page_id": result.get("id", ""),
                    "url": result.get("url", ""),
                    "title": title,
                },
            )

        except Exception as exc:
            logger.error("notion_create_page failed: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))
