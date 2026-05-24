"""MCP JSON-RPC client — communicates with MCP servers via stdio."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MCPClient:
    """JSON-RPC 2.0 client that talks to an MCP server via stdio."""

    def __init__(self, process: asyncio.subprocess.Process, server_name: str):
        self._process = process
        self._server_name = server_name
        self._request_id = 0
        self._tools: List[Dict[str, Any]] = []

    @property
    def is_alive(self) -> bool:
        return self._process.returncode is None

    async def initialize(self) -> None:
        """Send the MCP initialize handshake."""
        resp = await self._request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "spark", "version": "1.0.0"},
        })
        await self._notify("notifications/initialized", {})
        logger.info("MCP server '%s' initialized: %s", self._server_name, resp.get("serverInfo", {}))

    async def discover_tools(self) -> List[Dict[str, Any]]:
        """Call tools/list to discover available tools."""
        resp = await self._request("tools/list", {})
        self._tools = resp.get("tools", [])
        logger.info("MCP server '%s' exposes %d tools", self._server_name, len(self._tools))
        return self._tools

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Call a specific tool on the MCP server."""
        resp = await self._request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        # MCP returns {"content": [{"type": "text", "text": "..."}]}
        content = resp.get("content", [])
        if content and content[0].get("type") == "text":
            text = content[0]["text"]
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return text
        return content

    async def shutdown(self) -> None:
        """Gracefully shut down the MCP server."""
        try:
            await self._notify("notifications/cancelled", {})
            self._process.terminate()
            await asyncio.wait_for(self._process.wait(), timeout=5.0)
        except (asyncio.TimeoutError, ProcessLookupError):
            self._process.kill()

    # ── Internal ──────────────────────────────────────────────────────────

    async def _request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Send a JSON-RPC request and wait for the response."""
        self._request_id += 1
        msg = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }

        stdin = self._process.stdin
        stdout = self._process.stdout
        assert stdin and stdout

        line = json.dumps(msg) + "\n"
        stdin.write(line.encode())
        await stdin.drain()

        response_line = await asyncio.wait_for(stdout.readline(), timeout=30.0)
        response = json.loads(response_line.decode())

        if "error" in response:
            raise RuntimeError(f"MCP error: {response['error']}")

        return response.get("result", {})

    async def _notify(self, method: str, params: Dict[str, Any]) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        msg = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        stdin = self._process.stdin
        assert stdin
        line = json.dumps(msg) + "\n"
        stdin.write(line.encode())
        await stdin.drain()
