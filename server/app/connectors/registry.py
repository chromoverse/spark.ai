"""
Unified Connector Registry.

Single source of truth for:
- What services Spark can connect to
- What capabilities each service provides
- Whether a service uses native OAuth or MCP
- Current connection status per user
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from app.connectors.oauth.token_store import is_connected as _oauth_is_connected

logger = logging.getLogger(__name__)


class ConnectorType(str, Enum):
    OAUTH_NATIVE = "oauth_native"   # We handle OAuth + have native tool plugins
    MCP = "mcp"                     # External MCP server handles everything


@dataclass
class ConnectorDef:
    """Definition of a single external service connector."""
    id: str                                    # e.g. "gmail", "slack", "notion"
    display_name: str                          # e.g. "Gmail", "Slack"
    type: ConnectorType
    description: str                           # One-liner for UI
    icon: str = ""                             # Icon identifier or URL
    capabilities: List[str] = field(default_factory=list)  # ["email_read", "email_send"]
    plugin: Optional[str] = None               # Plugin that owns the tools (e.g. "google")
    mcp_server: Optional[str] = None           # MCP server name (for type=MCP)
    oauth_provider: Optional[str] = None       # Key in providers.py (for type=OAUTH_NATIVE)
    scopes_display: List[str] = field(default_factory=list)  # Human-readable scope descriptions
    requires_setup: bool = False               # Does user need to provide API keys?


# ── Registry ─────────────────────────────────────────────────────────────────

CONNECTORS: Dict[str, ConnectorDef] = {
    "gmail": ConnectorDef(
        id="gmail",
        display_name="Gmail",
        type=ConnectorType.OAUTH_NATIVE,
        description="Read, send, search, and organize emails",
        icon="gmail",
        capabilities=["email_read", "email_send", "email_search", "email_organize"],
        plugin="google",
        oauth_provider="gmail",
        scopes_display=["Read and modify your emails"],
    ),
    "google_calendar": ConnectorDef(
        id="google_calendar",
        display_name="Google Calendar",
        type=ConnectorType.OAUTH_NATIVE,
        description="View, create, and manage calendar events",
        icon="google_calendar",
        capabilities=["calendar_read", "calendar_write", "calendar_search"],
        plugin="google",
        oauth_provider="google_calendar",
        scopes_display=["Manage your calendar events"],
    ),
    "google_drive": ConnectorDef(
        id="google_drive",
        display_name="Google Drive",
        type=ConnectorType.OAUTH_NATIVE,
        description="Search, read, and manage files in Drive",
        icon="google_drive",
        capabilities=["file_read", "file_search", "file_upload"],
        plugin="google",
        oauth_provider="google_drive",
        scopes_display=["Access your Google Drive files"],
    ),
    "slack": ConnectorDef(
        id="slack",
        display_name="Slack",
        type=ConnectorType.OAUTH_NATIVE,
        description="Send messages, read channels, search conversations",
        icon="slack",
        capabilities=["message_send", "channel_read", "message_search"],
        plugin="slack",
        oauth_provider="slack",
        scopes_display=["Read channels", "Send messages"],
    ),
    "notion": ConnectorDef(
        id="notion",
        display_name="Notion",
        type=ConnectorType.MCP,
        description="Search pages, read content, manage databases",
        icon="notion",
        capabilities=["page_read", "page_search", "database_query"],
        mcp_server="notion",
        scopes_display=["Access your Notion workspace"],
    ),
    "github": ConnectorDef(
        id="github",
        display_name="GitHub",
        type=ConnectorType.MCP,
        description="View repos, issues, PRs, and notifications",
        icon="github",
        capabilities=["repo_read", "issue_read", "pr_read", "notification_read"],
        mcp_server="github",
        requires_setup=True,  # needs personal access token
        scopes_display=["Read your repositories and notifications"],
    ),
}


# ── Public API ────────────────────────────────────────────────────────────────

def get_connector(connector_id: str) -> ConnectorDef:
    """Get a connector definition by ID. Raises ValueError if not found."""
    if connector_id not in CONNECTORS:
        raise ValueError(f"Unknown connector: '{connector_id}'. Available: {list(CONNECTORS.keys())}")
    return CONNECTORS[connector_id]


def list_connectors() -> List[ConnectorDef]:
    """Return all registered connectors."""
    return list(CONNECTORS.values())


async def get_connector_status(user_id: str, connector_id: str) -> dict:
    """
    Check connection status for a specific connector.

    Returns:
        {"connected": bool, "account": str|None, "capabilities": [...]}
    """
    connector = get_connector(connector_id)

    if connector.type == ConnectorType.OAUTH_NATIVE:
        connected = await _oauth_is_connected(user_id, connector.oauth_provider)
    elif connector.type == ConnectorType.MCP:
        from app.connectors.mcp.manager import get_mcp_manager
        connected = get_mcp_manager().is_server_running(connector.mcp_server)
    else:
        connected = False

    return {
        "id": connector.id,
        "display_name": connector.display_name,
        "type": connector.type.value,
        "connected": connected,
        "capabilities": connector.capabilities,
        "description": connector.description,
        "icon": connector.icon,
        "requires_setup": connector.requires_setup,
    }


async def get_all_connector_statuses(user_id: str) -> List[dict]:
    """Return status of all connectors for a user (for frontend dashboard)."""
    statuses = []
    for connector_id in CONNECTORS:
        status = await get_connector_status(user_id, connector_id)
        statuses.append(status)
    return statuses
