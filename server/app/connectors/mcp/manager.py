"""MCP Server Manager — spawn, lifecycle, and health for MCP server processes."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.connectors.mcp.client import MCPClient

logger = logging.getLogger(__name__)

_SERVERS_JSON = Path(__file__).parent / "servers.json"
_IDLE_TIMEOUT = 600  # Kill servers idle for 10+ minutes


class MCPServerInstance:
    """Tracks a single running MCP server."""

    def __init__(self, name: str, client: MCPClient):
        self.name = name
        self.client = client
        self.tools: List[Dict[str, Any]] = []
        self.last_used: float = time.time()
        self.started_at: float = time.time()

    def touch(self) -> None:
        self.last_used = time.time()

    @property
    def idle_seconds(self) -> float:
        return time.time() - self.last_used


class MCPManager:
    """Manages MCP server processes — spawn on demand, kill when idle."""

    def __init__(self):
        self._servers: Dict[str, MCPServerInstance] = {}
        self._configs: Dict[str, Dict[str, Any]] = {}
        self._load_configs()

    def _load_configs(self) -> None:
        """Load server configurations from servers.json."""
        if _SERVERS_JSON.exists():
            with open(_SERVERS_JSON) as f:
                self._configs = json.load(f)

    def is_server_running(self, server_name: str) -> bool:
        """Check if a server is currently running."""
        instance = self._servers.get(server_name)
        return instance is not None and instance.client.is_alive

    def get_available_servers(self) -> List[str]:
        """Return names of all configured MCP servers."""
        return list(self._configs.keys())

    async def get_server(self, server_name: str) -> MCPServerInstance:
        """
        Get a running MCP server instance (lazy-spawn if not running).
        This is the main entry point for tool execution.
        """
        if server_name in self._servers and self._servers[server_name].client.is_alive:
            self._servers[server_name].touch()
            return self._servers[server_name]

        return await self._spawn(server_name)

    async def call_tool(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """High-level: call a tool on an MCP server (spawns if needed)."""
        instance = await self.get_server(server_name)
        instance.touch()
        return await instance.client.call_tool(tool_name, arguments)

    async def discover_tools(self, server_name: str) -> List[Dict[str, Any]]:
        """Discover tools from a server (spawns if needed)."""
        instance = await self.get_server(server_name)
        return instance.tools

    async def shutdown_server(self, server_name: str) -> None:
        """Gracefully shut down a specific MCP server."""
        if server_name in self._servers:
            await self._servers[server_name].client.shutdown()
            del self._servers[server_name]
            logger.info("MCP server '%s' shut down", server_name)

    async def shutdown_all(self) -> None:
        """Shut down all running MCP servers (call on app shutdown)."""
        for name in list(self._servers.keys()):
            await self.shutdown_server(name)

    async def cleanup_idle(self) -> None:
        """Kill servers that have been idle too long. Call periodically."""
        for name, instance in list(self._servers.items()):
            if instance.idle_seconds > _IDLE_TIMEOUT:
                logger.info("Killing idle MCP server: %s (idle %.0fs)", name, instance.idle_seconds)
                await self.shutdown_server(name)

    # ── Internal ──────────────────────────────────────────────────────────

    async def _spawn(self, server_name: str) -> MCPServerInstance:
        """Spawn a new MCP server subprocess."""
        if server_name not in self._configs:
            raise ValueError(f"Unknown MCP server: '{server_name}'. Check servers.json.")

        config = self._configs[server_name]
        command = config["command"]
        args = config.get("args", [])

        # Resolve env vars (${VAR_NAME} → actual value)
        env = os.environ.copy()
        for key, value in config.get("env", {}).items():
            if value.startswith("${") and value.endswith("}"):
                env_var = value[2:-1]
                resolved = os.getenv(env_var, "")
                if not resolved:
                    raise RuntimeError(
                        f"MCP server '{server_name}' requires env var {env_var} but it's not set."
                    )
                env[key] = resolved
            else:
                env[key] = value

        logger.info("Spawning MCP server: %s (%s %s)", server_name, command, " ".join(args))

        process = await asyncio.create_subprocess_exec(
            command, *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        client = MCPClient(process, server_name)
        await client.initialize()
        tools = await client.discover_tools()

        instance = MCPServerInstance(name=server_name, client=client)
        instance.tools = tools
        self._servers[server_name] = instance

        logger.info("MCP server '%s' ready with %d tools", server_name, len(tools))
        return instance


# ── Singleton ─────────────────────────────────────────────────────────────────

_manager: Optional[MCPManager] = None


def get_mcp_manager() -> MCPManager:
    global _manager
    if _manager is None:
        _manager = MCPManager()
    return _manager
