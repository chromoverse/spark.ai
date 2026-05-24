# Connectors Implementation Guide

> Step-by-step guide for building Spark's unified external service connector system.
> Follow each phase in order. Do NOT skip ahead.

---

## Context & Goal

Spark needs to connect to external platforms (Gmail, Calendar, Drive, Slack, Notion, GitHub, etc.) so a user can say "organize my day" and Spark pulls data from everywhere into one place.

**Current state:** Gmail works via a custom OAuth + plugin system. Nothing else is connected.

**Target state:** A clean `app/connectors/` module that handles:
- OAuth for any provider (Google, Slack, Microsoft, etc.)
- Authenticated API clients per service
- MCP integration for community-built connectors
- Rate limiting + audit logging as middleware
- A unified registry the frontend can query to show "Connected Services"

---

## Architecture Overview

```
server/app/connectors/
├── __init__.py
├── registry.py                  # "What services exist? What's connected?"
├── router.py                    # FastAPI: /connectors/list, status, capabilities
│
├── oauth/                       # Generic OAuth machinery
│   ├── __init__.py
│   ├── flow.py                  # /connect, /callback, /disconnect endpoints
│   ├── token_store.py           # Save/get/revoke refresh tokens (MongoDB + LocalKV)
│   ├── token_refresh.py         # Access token lifecycle (cache + refresh)
│   ├── encryption.py            # Fernet encrypt/decrypt
│   └── providers.py             # Per-provider OAuth configs
│
├── clients/                     # Authenticated API client builders
│   ├── __init__.py
│   ├── base.py                  # Base client with caching pattern
│   ├── gmail.py                 # get_gmail_service()
│   ├── calendar.py              # get_calendar_service()
│   ├── drive.py                 # get_drive_service()
│   └── slack.py                 # get_slack_client()
│
├── mcp/                         # MCP client layer
│   ├── __init__.py
│   ├── manager.py               # Spawn/kill/health-check MCP server processes
│   ├── client.py                # JSON-RPC transport (stdio + HTTP)
│   ├── adapter.py               # MCP tool → BaseTool interface wrapper
│   └── servers.json             # Registry of known MCP server configs
│
└── middleware/                   # Cross-cutting concerns
    ├── __init__.py
    ├── rate_limiter.py           # Per-service per-user sliding window
    └── audit.py                  # Kernel event logging for all connector actions
```

---

## Phase 1: Directory Migration (Move Existing Code)

> Goal: Move existing code from scattered locations into `app/connectors/` without breaking anything.

### Step 1.1: Create the directory structure

```bash
mkdir -p server/app/connectors/oauth
mkdir -p server/app/connectors/clients
mkdir -p server/app/connectors/mcp
mkdir -p server/app/connectors/middleware
```

Create `__init__.py` in each:

```python
# server/app/connectors/__init__.py
"""Unified external service connector system."""

# server/app/connectors/oauth/__init__.py
"""OAuth 2.0 flow, token storage, and provider configs."""

# server/app/connectors/clients/__init__.py
"""Authenticated API client builders for external services."""

# server/app/connectors/mcp/__init__.py
"""MCP (Model Context Protocol) client layer for community connectors."""

# server/app/connectors/middleware/__init__.py
"""Cross-cutting connector middleware: rate limiting, audit logging."""
```

### Step 1.2: Move OAuth files

| From | To | Rename? |
|------|----|---------|
| `app/features/external_service/encryption.py` | `app/connectors/oauth/encryption.py` | No |
| `app/features/external_service/providers.py` | `app/connectors/oauth/providers.py` | No |
| `app/features/external_service/oauth_token_service.py` | `app/connectors/oauth/token_store.py` | Yes |
| `app/features/external_service/token_manager.py` | `app/connectors/oauth/token_refresh.py` | Yes |
| `app/features/external_service/router.py` | `app/connectors/oauth/flow.py` | Yes |

After moving, update all internal imports. The public API from `oauth/` should be:

```python
# server/app/connectors/oauth/__init__.py
from app.connectors.oauth.token_store import save_token, get_refresh_token, revoke_token, is_connected
from app.connectors.oauth.token_refresh import get_valid_access_token, clear_access_token_cache
from app.connectors.oauth.encryption import encrypt_token, decrypt_token
from app.connectors.oauth.providers import get_provider, get_client_id, get_client_secret, get_redirect_uri, PROVIDERS
```

### Step 1.3: Move middleware files

| From | To |
|------|----|
| `app/features/bridge/rate_limiter.py` | `app/connectors/middleware/rate_limiter.py` |

Create new `app/connectors/middleware/audit.py` (extract from action_bridge):

```python
"""Connector audit logging via kernel events."""
import logging
from app.kernel.contracts.models import KernelEvent
from app.kernel.eventing.event_bus import emit_kernel_event

logger = logging.getLogger(__name__)


async def log_connector_action(
    user_id: str,
    service: str,
    action: str,
    success: bool,
    error: str = "",
) -> None:
    """Emit a kernel event for any connector action (for activity log)."""
    await emit_kernel_event(KernelEvent(
        event_type="task_completed" if success else "task_failed",
        user_id=user_id,
        tool_name=f"{service}:{action}",
        status="completed" if success else "failed",
        payload={"service": service, "action": action, "error": error},
    ))
```

### Step 1.4: Move client files

Merge `app/features/gmail/_client.py` + `shared/service_client.py` into `app/connectors/clients/gmail.py`:

```python
"""Gmail API client builder with in-memory caching."""
import logging
import time
from typing import Any, Dict, Optional, Tuple

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.connectors.oauth.token_refresh import get_valid_access_token

logger = logging.getLogger(__name__)

_SERVICE_CACHE: Dict[Tuple[str, Optional[str]], Tuple[float, Any]] = {}
_CACHE_TTL = 3000  # 50 minutes (access tokens last 60 min)


async def get_gmail_service(user_id: str, account_email: Optional[str] = None):
    """
    Build and return an authenticated Gmail API service object.
    Caches the service instance for 50 minutes to avoid re-building.

    This is the ONLY entry point for Gmail API access.
    Tools call this — they never touch tokens directly.
    """
    cache_key = (user_id, account_email)
    now = time.time()

    if cache_key in _SERVICE_CACHE:
        cached_time, cached_service = _SERVICE_CACHE[cache_key]
        if now - cached_time < _CACHE_TTL:
            return cached_service

    access_token = await get_valid_access_token(
        user_id=user_id,
        service="gmail",
        account_email=account_email,
    )

    if not access_token:
        raise RuntimeError(f"No Gmail access token for user {user_id}. Please connect Gmail.")

    creds = Credentials(token=access_token)
    service = build("gmail", "v1", credentials=creds)

    _SERVICE_CACHE[cache_key] = (now, service)
    logger.debug("Gmail service built for user=%s", user_id)
    return service
```

### Step 1.5: Update all imports across the codebase

After moving files, grep for old import paths and update them:

Old:
```python
from app.features.external_service.oauth_token_service import save_token, revoke_token, is_connected
from app.features.external_service.token_manager import get_valid_access_token
from app.features.external_service.providers import get_provider, PROVIDERS
from app.features.bridge.action_bridge import get_action_bridge
from app.features.gmail._client import get_gmail_service
from shared.service_client import get_gmail_service
```

New:
```python
from app.connectors.oauth import save_token, revoke_token, is_connected
from app.connectors.oauth import get_valid_access_token
from app.connectors.oauth.providers import get_provider, PROVIDERS
from app.connectors.clients.gmail import get_gmail_service
```

Files that need import updates:
- `plugins/installed/google/tools/gmail.py` — change `from shared.service_client import get_gmail_service` to `from app.connectors.clients.gmail import get_gmail_service`
- `plugins/installed/google/tools/gmail_bridge.py` — same
- Any file importing from `app.features.external_service.*`
- Any file importing from `app.features.bridge.*`

### Step 1.6: Add backward-compatibility shims (temporary)

To avoid breaking things during migration, add re-exports in the old locations:

```python
# server/app/features/external_service/__init__.py (temporary shim)
"""DEPRECATED: Use app.connectors.oauth instead. Will be removed."""
from app.connectors.oauth.token_store import save_token, get_refresh_token, revoke_token, is_connected
from app.connectors.oauth.token_refresh import get_valid_access_token, clear_access_token_cache
from app.connectors.oauth.encryption import encrypt_token, decrypt_token
```

Delete these shims once all imports are updated and tests pass.

### Step 1.7: Delete old files

Once all imports point to new locations and the server starts clean:
- Delete `app/features/external_service/` (entire directory)
- Delete `app/features/bridge/` (entire directory)
- Delete `app/features/gmail/` (entire directory)
- Delete `shared/service_client.py`
- Delete `plugins/installed/google/tools/gmail_bridge.py` (redundant once middleware is standard)

### Step 1.8: Verify

```bash
cd server
python -c "from app.connectors.oauth import get_valid_access_token, is_connected, PROVIDERS; print('OAuth OK')"
python -c "from app.connectors.clients.gmail import get_gmail_service; print('Client OK')"
python -c "from app.connectors.middleware.rate_limiter import RateLimiter; print('Middleware OK')"
```

Run existing tests. Make sure Gmail tools still work end-to-end.

---

## Phase 2: Unified Connector Registry

> Goal: A single source of truth for "what services does Spark support, what's connected for this user, what can each service do."

### Step 2.1: Create the registry

```python
# server/app/connectors/registry.py
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
```

### Step 2.2: Create the connectors API router

```python
# server/app/connectors/router.py
"""
Connector API routes — frontend-facing.

These endpoints power the "Connected Services" UI in Spark.
"""
from fastapi import APIRouter
from typing import Optional

from app.connectors.registry import (
    get_all_connector_statuses,
    get_connector_status,
    get_connector,
    list_connectors,
)

router = APIRouter(prefix="/connectors", tags=["Connectors"])


@router.get("/list")
async def list_all_connectors(user_id: str):
    """
    Return all available connectors with their connection status.
    Frontend uses this to render the Connected Services grid.
    """
    return await get_all_connector_statuses(user_id)


@router.get("/{connector_id}/status")
async def connector_status(connector_id: str, user_id: str):
    """Check if a specific connector is connected for this user."""
    return await get_connector_status(user_id, connector_id)


@router.get("/{connector_id}/capabilities")
async def connector_capabilities(connector_id: str):
    """Return what a connector can do (for tool selection logic)."""
    connector = get_connector(connector_id)
    return {
        "id": connector.id,
        "capabilities": connector.capabilities,
        "scopes_display": connector.scopes_display,
    }
```

### Step 2.3: Register the routers in the FastAPI app

In your main FastAPI app setup (likely `server/app/main.py` or wherever routes are included):

```python
from app.connectors.router import router as connectors_router
from app.connectors.oauth.flow import router as oauth_flow_router

app.include_router(connectors_router)
app.include_router(oauth_flow_router)
```

---

## Phase 3: Add New OAuth Providers

> Goal: Enable Google Calendar, Google Drive, and Slack in the provider registry.

### Step 3.1: Update providers.py with new services

```python
# server/app/connectors/oauth/providers.py
# Add these entries to the PROVIDERS dict:

PROVIDERS: Dict[str, Dict[str, Any]] = {
    # ── existing ──
    "gmail": {
        "display_name": "Gmail",
        "scopes": [
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/userinfo.email",
        ],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "userinfo_uri": "https://www.googleapis.com/oauth2/v2/userinfo",
        "client_id_env": "GOOGLE_CLIENT_ID",
        "client_secret_env": "GOOGLE_CLIENT_SECRET",
        "redirect_uri_env": "GOOGLE_REDIRECT_URI",
        "default_redirect_uri": "http://localhost:8000/auth/gmail/callback",
    },
    "google_calendar": {
        "display_name": "Google Calendar",
        "scopes": [
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/userinfo.email",
        ],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "userinfo_uri": "https://www.googleapis.com/oauth2/v2/userinfo",
        "client_id_env": "GOOGLE_CLIENT_ID",
        "client_secret_env": "GOOGLE_CLIENT_SECRET",
        "redirect_uri_env": "GOOGLE_CALENDAR_REDIRECT_URI",
        "default_redirect_uri": "http://localhost:8000/auth/google_calendar/callback",
    },

    # ── new: Google Drive ──
    "google_drive": {
        "display_name": "Google Drive",
        "scopes": [
            "https://www.googleapis.com/auth/drive.readonly",
            "https://www.googleapis.com/auth/userinfo.email",
        ],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "userinfo_uri": "https://www.googleapis.com/oauth2/v2/userinfo",
        "client_id_env": "GOOGLE_CLIENT_ID",
        "client_secret_env": "GOOGLE_CLIENT_SECRET",
        "redirect_uri_env": "GOOGLE_DRIVE_REDIRECT_URI",
        "default_redirect_uri": "http://localhost:8000/auth/google_drive/callback",
    },

    # ── new: Slack ──
    "slack": {
        "display_name": "Slack",
        "scopes": [
            "channels:read",
            "channels:history",
            "chat:write",
            "search:read",
            "users:read",
        ],
        "auth_uri": "https://slack.com/oauth/v2/authorize",
        "token_uri": "https://slack.com/api/oauth.v2.access",
        "userinfo_uri": None,  # Slack doesn't use standard userinfo
        "client_id_env": "SLACK_CLIENT_ID",
        "client_secret_env": "SLACK_CLIENT_SECRET",
        "redirect_uri_env": "SLACK_REDIRECT_URI",
        "default_redirect_uri": "http://localhost:8000/auth/slack/callback",
    },
}
```

### Step 3.2: Handle non-Google OAuth flows

The current `flow.py` uses `google_auth_oauthlib.flow.Flow` which only works for Google. For Slack and others, you need a generic OAuth 2.0 handler.

Update `flow.py` (previously `router.py`) to branch on provider type:

```python
# In app/connectors/oauth/flow.py, add:

async def _generic_oauth_connect(service: str, user_id: str) -> str:
    """Build OAuth authorization URL for non-Google providers (Slack, etc.)."""
    cfg = get_provider(service)
    redirect_uri = get_redirect_uri(service)

    params = {
        "client_id": os.getenv(cfg["client_id_env"]),
        "scope": " ".join(cfg["scopes"]),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": f"{service}:{user_id}",
    }

    auth_url = f"{cfg['auth_uri']}?{'&'.join(f'{k}={v}' for k, v in params.items())}"
    return auth_url


async def _generic_oauth_callback(service: str, code: str, user_id: str) -> dict:
    """Exchange auth code for tokens using standard OAuth 2.0 (non-Google)."""
    cfg = get_provider(service)
    redirect_uri = get_redirect_uri(service)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            cfg["token_uri"],
            data={
                "client_id": os.getenv(cfg["client_id_env"]),
                "client_secret": os.getenv(cfg["client_secret_env"]),
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )

    data = resp.json()
    if "error" in data:
        raise HTTPException(status_code=400, detail=f"OAuth error: {data['error']}")

    # Slack uses "authed_user.access_token" nested structure
    access_token = data.get("access_token") or data.get("authed_user", {}).get("access_token")
    refresh_token = data.get("refresh_token")

    # For Slack: access tokens don't expire, so we store the access_token AS the refresh_token
    if not refresh_token and access_token:
        refresh_token = access_token

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "team": data.get("team", {}).get("name"),
    }
```

Then in the main `/connect` endpoint, branch:

```python
@router.get("/{service}/connect")
async def oauth_connect(service: str, request: Request, user_id: str):
    cfg = get_provider(service)

    # Google services use the google-auth-oauthlib Flow
    if "google" in cfg["auth_uri"]:
        flow = _build_google_flow(service)
        auth_url, state = flow.authorization_url(
            access_type="offline", prompt="consent",
            state=f"{service}:{user_id}", include_granted_scopes="true",
        )
        # ... (existing code)
        return RedirectResponse(auth_url)

    # All other providers use generic OAuth 2.0
    auth_url = await _generic_oauth_connect(service, user_id)
    return RedirectResponse(auth_url)
```

### Step 3.3: Add env vars to your .env

```env
# Google (shared across Gmail, Calendar, Drive)
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/gmail/callback
GOOGLE_CALENDAR_REDIRECT_URI=http://localhost:8000/auth/google_calendar/callback
GOOGLE_DRIVE_REDIRECT_URI=http://localhost:8000/auth/google_drive/callback

# Slack
SLACK_CLIENT_ID=your_slack_client_id
SLACK_CLIENT_SECRET=your_slack_client_secret
SLACK_REDIRECT_URI=http://localhost:8000/auth/slack/callback

# Token encryption (already exists)
TOKEN_ENCRYPTION_KEY=your_fernet_key
```

---

## Phase 4: Build Service Clients

> Goal: Each connected service gets a client builder in `connectors/clients/`.

### Step 4.1: Base client pattern

```python
# server/app/connectors/clients/base.py
"""Base pattern for service clients with caching."""
import time
import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class ClientCache:
    """Simple TTL cache for authenticated service clients."""

    def __init__(self, ttl_seconds: int = 3000):
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._ttl = ttl_seconds

    def get(self, key: str) -> Optional[Any]:
        if key in self._cache:
            cached_time, client = self._cache[key]
            if time.time() - cached_time < self._ttl:
                return client
            del self._cache[key]
        return None

    def set(self, key: str, client: Any) -> None:
        self._cache[key] = (time.time(), client)

    def invalidate(self, key: str) -> None:
        self._cache.pop(key, None)
```

### Step 4.2: Google Calendar client

```python
# server/app/connectors/clients/calendar.py
"""Google Calendar API client builder."""
import logging
from typing import Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.connectors.oauth.token_refresh import get_valid_access_token
from app.connectors.clients.base import ClientCache

logger = logging.getLogger(__name__)
_cache = ClientCache(ttl_seconds=3000)


async def get_calendar_service(user_id: str, account_email: Optional[str] = None):
    """
    Build and return an authenticated Google Calendar API service.
    Tools call this — they never touch tokens directly.
    """
    cache_key = f"{user_id}:{account_email or 'default'}"
    cached = _cache.get(cache_key)
    if cached:
        return cached

    access_token = await get_valid_access_token(
        user_id=user_id,
        service="google_calendar",
        account_email=account_email,
    )
    if not access_token:
        raise RuntimeError(f"No Calendar token for user {user_id}. Please connect Google Calendar.")

    creds = Credentials(token=access_token)
    service = build("calendar", "v3", credentials=creds)
    _cache.set(cache_key, service)
    return service
```

### Step 4.3: Google Drive client

```python
# server/app/connectors/clients/drive.py
"""Google Drive API client builder."""
import logging
from typing import Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.connectors.oauth.token_refresh import get_valid_access_token
from app.connectors.clients.base import ClientCache

logger = logging.getLogger(__name__)
_cache = ClientCache(ttl_seconds=3000)


async def get_drive_service(user_id: str, account_email: Optional[str] = None):
    """Build authenticated Google Drive API service."""
    cache_key = f"{user_id}:{account_email or 'default'}"
    cached = _cache.get(cache_key)
    if cached:
        return cached

    access_token = await get_valid_access_token(
        user_id=user_id,
        service="google_drive",
        account_email=account_email,
    )
    if not access_token:
        raise RuntimeError(f"No Drive token for user {user_id}. Please connect Google Drive.")

    creds = Credentials(token=access_token)
    service = build("drive", "v3", credentials=creds)
    _cache.set(cache_key, service)
    return service
```

### Step 4.4: Slack client

```python
# server/app/connectors/clients/slack.py
"""Slack Web API client builder."""
import logging
from typing import Optional

import httpx

from app.connectors.oauth.token_refresh import get_valid_access_token
from app.connectors.clients.base import ClientCache

logger = logging.getLogger(__name__)
_cache = ClientCache(ttl_seconds=3000)


class SlackClient:
    """Lightweight Slack Web API wrapper."""

    def __init__(self, access_token: str):
        self._token = access_token
        self._base = "https://slack.com/api"

    async def _call(self, method: str, **kwargs) -> dict:
        """Make an authenticated Slack API call."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._base}/{method}",
                headers={"Authorization": f"Bearer {self._token}"},
                json=kwargs if kwargs else None,
            )
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack API error: {data.get('error', 'unknown')}")
        return data

    async def list_channels(self, limit: int = 50) -> list:
        data = await self._call("conversations.list", limit=limit, types="public_channel,private_channel")
        return data.get("channels", [])

    async def channel_history(self, channel_id: str, limit: int = 20) -> list:
        data = await self._call("conversations.history", channel=channel_id, limit=limit)
        return data.get("messages", [])

    async def send_message(self, channel_id: str, text: str) -> dict:
        return await self._call("chat.postMessage", channel=channel_id, text=text)

    async def search_messages(self, query: str, count: int = 20) -> list:
        data = await self._call("search.messages", query=query, count=count)
        return data.get("messages", {}).get("matches", [])


async def get_slack_client(user_id: str, account_email: Optional[str] = None) -> SlackClient:
    """Build authenticated Slack client."""
    cache_key = f"{user_id}:{account_email or 'default'}"
    cached = _cache.get(cache_key)
    if cached:
        return cached

    access_token = await get_valid_access_token(
        user_id=user_id,
        service="slack",
        account_email=account_email,
    )
    if not access_token:
        raise RuntimeError(f"No Slack token for user {user_id}. Please connect Slack.")

    client = SlackClient(access_token)
    _cache.set(cache_key, client)
    return client
```

---

## Phase 5: MCP Integration

> Goal: Spark can talk to any MCP server, discover its tools, and call them through the standard BaseTool interface.

### Step 5.1: MCP server config

```json
// server/app/connectors/mcp/servers.json
{
  "notion": {
    "display_name": "Notion",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-notion"],
    "env": {
      "NOTION_API_KEY": "${NOTION_API_KEY}"
    },
    "transport": "stdio",
    "auto_start": false,
    "lazy_spawn": true
  },
  "github": {
    "display_name": "GitHub",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-github"],
    "env": {
      "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}"
    },
    "transport": "stdio",
    "auto_start": false,
    "lazy_spawn": true
  },
  "spotify": {
    "display_name": "Spotify",
    "command": "npx",
    "args": ["-y", "mcp-spotify"],
    "env": {
      "SPOTIFY_CLIENT_ID": "${SPOTIFY_CLIENT_ID}",
      "SPOTIFY_CLIENT_SECRET": "${SPOTIFY_CLIENT_SECRET}"
    },
    "transport": "stdio",
    "auto_start": false,
    "lazy_spawn": true
  }
}
```

### Step 5.2: MCP client (JSON-RPC over stdio)

```python
# server/app/connectors/mcp/client.py
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
        # After initialize, send initialized notification
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
            # Try to parse as JSON
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

        # Read response line
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
```

### Step 5.3: MCP server manager

```python
# server/app/connectors/mcp/manager.py
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
```

### Step 5.4: MCP tool adapter (makes MCP tools look like BaseTool)

```python
# server/app/connectors/mcp/adapter.py
"""Adapts MCP tools to the BaseTool interface so the orchestrator treats them uniformly."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.plugins.tools.tool_base import BaseTool, ToolOutput
from app.connectors.mcp.manager import get_mcp_manager

logger = logging.getLogger(__name__)


class MCPToolAdapter(BaseTool):
    """
    Wraps a single MCP tool as a BaseTool.

    Created dynamically when MCP servers are discovered.
    The orchestrator and SQH see these identically to native tools.
    """

    def __init__(self, server_name: str, tool_def: Dict[str, Any]):
        super().__init__()
        self._server_name = server_name
        self._tool_name = tool_def["name"]
        self._tool_def = tool_def

        # Set BaseTool class attributes from MCP tool definition
        self.TOOL_DESCRIPTION = tool_def.get("description", "")
        self.EXECUTION_TARGET = "server"
        self.PARAMS_SCHEMA = self._convert_schema(tool_def.get("inputSchema", {}))
        self.OUTPUT_SCHEMA = {"success": {"type": "boolean"}, "data": {"type": "object"}, "error": {"type": "string"}}
        self.SEMANTIC_TAGS = [server_name, self._tool_name]
        self.TOOL_CATEGORY = "external"
        self.EXAMPLES = []
        self.METADATA: Dict[str, Any] = {"source": "mcp", "server": server_name}

    def get_tool_name(self) -> str:
        return self._tool_name

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        """Execute the tool via MCP JSON-RPC call."""
        try:
            # Strip internal fields before sending to MCP
            clean_inputs = {
                k: v for k, v in inputs.items()
                if not k.startswith("_")
            }
            clean_inputs.pop("user_id", None)

            result = await get_mcp_manager().call_tool(
                self._server_name, self._tool_name, clean_inputs
            )

            if isinstance(result, dict):
                return ToolOutput(success=True, data=result)
            return ToolOutput(success=True, data={"result": result})

        except Exception as exc:
            logger.error("MCP tool %s:%s failed: %s", self._server_name, self._tool_name, exc)
            return ToolOutput(success=False, data={}, error=str(exc))

    @staticmethod
    def _convert_schema(json_schema: Dict[str, Any]) -> Dict[str, Any]:
        """Convert JSON Schema (MCP format) to BaseTool PARAMS_SCHEMA format."""
        params = {}
        properties = json_schema.get("properties", {})
        required = json_schema.get("required", [])

        for name, prop in properties.items():
            params[name] = {
                "type": prop.get("type", "string"),
                "required": name in required,
                "description": prop.get("description", ""),
            }
            if "default" in prop:
                params[name]["default"] = prop["default"]

        return params


def create_mcp_tool_adapters(server_name: str, tools: List[Dict[str, Any]]) -> List[MCPToolAdapter]:
    """Create BaseTool-compatible adapters for all tools from an MCP server."""
    adapters = []
    for tool_def in tools:
        adapter = MCPToolAdapter(server_name, tool_def)
        adapters.append(adapter)
    return adapters
```

### Step 5.5: Register MCP tools in the plugin registry at boot

Add this to your server startup (where plugins are loaded):

```python
# In server startup code (e.g., app/main.py or plugins/manager.py):

async def register_mcp_tools():
    """Discover and register MCP tools for connected services."""
    from app.connectors.mcp.manager import get_mcp_manager
    from app.connectors.mcp.adapter import create_mcp_tool_adapters
    from app.plugins.tools.registry_loader import tool_registry, ToolMetadata

    manager = get_mcp_manager()

    for server_name in manager.get_available_servers():
        # Only spawn servers that the user has configured (has env vars set)
        try:
            tools = await manager.discover_tools(server_name)
        except Exception as e:
            logger.warning("Skipping MCP server '%s': %s", server_name, e)
            continue

        adapters = create_mcp_tool_adapters(server_name, tools)
        for adapter in adapters:
            meta = ToolMetadata(
                tool_name=adapter.get_tool_name(),
                description=adapter.TOOL_DESCRIPTION,
                execution_target="server",
                module=f"app.connectors.mcp.adapter",
                class_name="MCPToolAdapter",
                params_schema=adapter.PARAMS_SCHEMA,
                output_schema=adapter.OUTPUT_SCHEMA,
                metadata=adapter.METADATA,
                examples=[],
                semantic_tags=adapter.SEMANTIC_TAGS,
                category="external",
            )
            tool_registry.tools[meta.tool_name] = meta
            tool_registry.server_tools.append(meta.tool_name)

    logger.info("Registered %d MCP tools from %d servers",
                sum(len(s.tools) for s in manager._servers.values()),
                len(manager._servers))
```

---

## Phase 6: Build Tool Plugins for New Services

> Goal: Create actual tool implementations for Calendar, Drive, and Slack.

### Step 6.1: Google Calendar tools

```python
# server/plugins/installed/google/tools/calendar.py
"""Google Calendar tools — list events, create event, search events."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict

from app.connectors.clients.calendar import get_calendar_service
from app.plugins.tools.tool_base import BaseTool, ToolOutput

logger = logging.getLogger(__name__)


async def _svc(inputs: Dict[str, Any]):
    user_id = inputs.get("_user_id") or inputs.get("user_id")
    if not user_id:
        raise ValueError("user_id required")
    return await get_calendar_service(user_id=str(user_id))


class CalendarListEventsTool(BaseTool):
    """
    List upcoming calendar events.

    Inputs:
    - user_id (string, required)
    - days_ahead (integer, optional): How many days to look ahead (default: 1)
    - max_results (integer, optional): Max events to return (default: 10)

    Outputs:
    - events (array): [{summary, start, end, location, description, id}]
    - total (integer)
    """

    TOOL_DESCRIPTION = "List upcoming calendar events for today or coming days"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA = {
        "user_id": {"type": "string", "required": True},
        "days_ahead": {"type": "integer", "required": False, "default": 1, "description": "Days to look ahead"},
        "max_results": {"type": "integer", "required": False, "default": 10},
    }
    OUTPUT_SCHEMA = {
        "success": {"type": "boolean"},
        "data": {"events": {"type": "array"}, "total": {"type": "integer"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "what's on my calendar today"}]
    SEMANTIC_TAGS = ["calendar", "events", "schedule", "meetings", "today"]
    TOOL_CATEGORY = "productivity"

    def get_tool_name(self) -> str:
        return "calendar_list_events"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            service = await _svc(inputs)
            days_ahead = int(inputs.get("days_ahead", 1))
            max_results = int(inputs.get("max_results", 10))

            now = datetime.utcnow()
            time_min = now.isoformat() + "Z"
            time_max = (now + timedelta(days=days_ahead)).isoformat() + "Z"

            resp = service.events().list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            ).execute()

            events = []
            for item in resp.get("items", []):
                start = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date", "")
                end = item.get("end", {}).get("dateTime") or item.get("end", {}).get("date", "")
                events.append({
                    "id": item["id"],
                    "summary": item.get("summary", "(no title)"),
                    "start": start,
                    "end": end,
                    "location": item.get("location", ""),
                    "description": item.get("description", ""),
                    "status": item.get("status", ""),
                })

            return ToolOutput(success=True, data={"events": events, "total": len(events)})
        except Exception as exc:
            logger.error("calendar_list_events error: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))


class CalendarCreateEventTool(BaseTool):
    """
    Create a new calendar event.

    Inputs:
    - user_id (string, required)
    - summary (string, required): Event title
    - start_time (string, required): ISO datetime e.g. "2026-05-25T10:00:00"
    - end_time (string, required): ISO datetime
    - description (string, optional)
    - location (string, optional)

    Outputs:
    - event_id (string)
    - summary (string)
    - link (string): Google Calendar event link
    """

    TOOL_DESCRIPTION = "Create a new calendar event with time, title, and optional details"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA = {
        "user_id": {"type": "string", "required": True},
        "summary": {"type": "string", "required": True, "description": "Event title"},
        "start_time": {"type": "string", "required": True, "description": "ISO datetime"},
        "end_time": {"type": "string", "required": True, "description": "ISO datetime"},
        "description": {"type": "string", "required": False, "default": ""},
        "location": {"type": "string", "required": False, "default": ""},
    }
    OUTPUT_SCHEMA = {
        "success": {"type": "boolean"},
        "data": {"event_id": {"type": "string"}, "summary": {"type": "string"}, "link": {"type": "string"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "schedule a meeting tomorrow at 2pm"}]
    SEMANTIC_TAGS = ["calendar", "create", "event", "schedule", "meeting"]
    TOOL_CATEGORY = "productivity"

    def get_tool_name(self) -> str:
        return "calendar_create_event"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            service = await _svc(inputs)

            event_body = {
                "summary": inputs["summary"],
                "start": {"dateTime": inputs["start_time"], "timeZone": "Asia/Kolkata"},
                "end": {"dateTime": inputs["end_time"], "timeZone": "Asia/Kolkata"},
            }
            if inputs.get("description"):
                event_body["description"] = inputs["description"]
            if inputs.get("location"):
                event_body["location"] = inputs["location"]

            event = service.events().insert(calendarId="primary", body=event_body).execute()

            return ToolOutput(success=True, data={
                "event_id": event["id"],
                "summary": event.get("summary", ""),
                "link": event.get("htmlLink", ""),
            })
        except Exception as exc:
            logger.error("calendar_create_event error: %s", exc)
            return ToolOutput(success=False, data={}, error=str(exc))


__all__ = ["CalendarListEventsTool", "CalendarCreateEventTool"]
```

### Step 6.2: Slack tools

Create a new plugin:

```json
// server/plugins/installed/slack/plugin.json
{
  "name": "slack",
  "version": "1.0.0",
  "display_name": "Slack",
  "description": "Send messages, read channels, and search Slack conversations.",
  "author": "spark-core",
  "capabilities": ["message_send", "channel_read", "message_search"],
  "tools": ["slack_channels", "slack_messages", "slack_send", "slack_search"],
  "skills": [],
  "dependencies": [],
  "requires_oauth": ["slack"],
  "config_schema": {},
  "enabled": true
}
```

```python
# server/plugins/installed/slack/tools/__init__.py
from plugins.installed.slack.tools.channels import SlackChannelsTool
from plugins.installed.slack.tools.messages import SlackMessagesTool, SlackSendTool, SlackSearchTool
```

```python
# server/plugins/installed/slack/tools/channels.py
"""Slack channel tools."""
from __future__ import annotations
from typing import Any, Dict
from app.connectors.clients.slack import get_slack_client
from app.plugins.tools.tool_base import BaseTool, ToolOutput


class SlackChannelsTool(BaseTool):
    """
    List Slack channels the user has access to.

    Inputs:
    - user_id (string, required)
    - limit (integer, optional): Max channels (default: 30)

    Outputs:
    - channels (array): [{id, name, is_private, num_members}]
    """

    TOOL_DESCRIPTION = "List Slack channels accessible to the user"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA = {
        "user_id": {"type": "string", "required": True},
        "limit": {"type": "integer", "required": False, "default": 30},
    }
    OUTPUT_SCHEMA = {
        "success": {"type": "boolean"},
        "data": {"channels": {"type": "array"}, "total": {"type": "integer"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "show my slack channels"}]
    SEMANTIC_TAGS = ["slack", "channels", "list"]
    TOOL_CATEGORY = "communication"

    def get_tool_name(self) -> str:
        return "slack_channels"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            user_id = str(inputs.get("_user_id") or inputs.get("user_id"))
            client = await get_slack_client(user_id)
            limit = int(inputs.get("limit", 30))

            channels = await client.list_channels(limit=limit)
            result = [{
                "id": ch["id"],
                "name": ch["name"],
                "is_private": ch.get("is_private", False),
                "num_members": ch.get("num_members", 0),
            } for ch in channels]

            return ToolOutput(success=True, data={"channels": result, "total": len(result)})
        except Exception as exc:
            return ToolOutput(success=False, data={}, error=str(exc))
```

```python
# server/plugins/installed/slack/tools/messages.py
"""Slack messaging tools — read, send, search."""
from __future__ import annotations
from typing import Any, Dict
from app.connectors.clients.slack import get_slack_client
from app.plugins.tools.tool_base import BaseTool, ToolOutput


class SlackMessagesTool(BaseTool):
    """
    Read recent messages from a Slack channel.

    Inputs:
    - user_id (string, required)
    - channel_id (string, required)
    - limit (integer, optional): default 20

    Outputs:
    - messages (array): [{text, user, timestamp}]
    """

    TOOL_DESCRIPTION = "Read recent messages from a Slack channel"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA = {
        "user_id": {"type": "string", "required": True},
        "channel_id": {"type": "string", "required": True},
        "limit": {"type": "integer", "required": False, "default": 20},
    }
    OUTPUT_SCHEMA = {
        "success": {"type": "boolean"},
        "data": {"messages": {"type": "array"}, "total": {"type": "integer"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "read slack messages from general"}]
    SEMANTIC_TAGS = ["slack", "messages", "read", "channel"]
    TOOL_CATEGORY = "communication"

    def get_tool_name(self) -> str:
        return "slack_messages"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            user_id = str(inputs.get("_user_id") or inputs.get("user_id"))
            client = await get_slack_client(user_id)
            channel_id = inputs["channel_id"]
            limit = int(inputs.get("limit", 20))

            messages = await client.channel_history(channel_id, limit=limit)
            result = [{
                "text": m.get("text", ""),
                "user": m.get("user", ""),
                "timestamp": m.get("ts", ""),
            } for m in messages]

            return ToolOutput(success=True, data={"messages": result, "total": len(result)})
        except Exception as exc:
            return ToolOutput(success=False, data={}, error=str(exc))


class SlackSendTool(BaseTool):
    """
    Send a message to a Slack channel.

    Inputs:
    - user_id (string, required)
    - channel_id (string, required)
    - text (string, required)

    Outputs:
    - sent (boolean)
    - channel (string)
    - timestamp (string)
    """

    TOOL_DESCRIPTION = "Send a message to a Slack channel"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA = {
        "user_id": {"type": "string", "required": True},
        "channel_id": {"type": "string", "required": True},
        "text": {"type": "string", "required": True},
    }
    OUTPUT_SCHEMA = {
        "success": {"type": "boolean"},
        "data": {"sent": {"type": "boolean"}, "channel": {"type": "string"}, "timestamp": {"type": "string"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "send a message on slack"}]
    SEMANTIC_TAGS = ["slack", "send", "message", "post"]
    TOOL_CATEGORY = "communication"

    def get_tool_name(self) -> str:
        return "slack_send"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            user_id = str(inputs.get("_user_id") or inputs.get("user_id"))
            client = await get_slack_client(user_id)

            resp = await client.send_message(inputs["channel_id"], inputs["text"])
            return ToolOutput(success=True, data={
                "sent": True,
                "channel": resp.get("channel", ""),
                "timestamp": resp.get("ts", ""),
            })
        except Exception as exc:
            return ToolOutput(success=False, data={}, error=str(exc))


class SlackSearchTool(BaseTool):
    """
    Search Slack messages across all channels.

    Inputs:
    - user_id (string, required)
    - query (string, required)
    - count (integer, optional): default 20

    Outputs:
    - matches (array): [{text, channel_name, user, timestamp, permalink}]
    - total (integer)
    """

    TOOL_DESCRIPTION = "Search Slack messages across all accessible channels"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA = {
        "user_id": {"type": "string", "required": True},
        "query": {"type": "string", "required": True, "description": "Search query"},
        "count": {"type": "integer", "required": False, "default": 20},
    }
    OUTPUT_SCHEMA = {
        "success": {"type": "boolean"},
        "data": {"matches": {"type": "array"}, "total": {"type": "integer"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "search slack for deployment"}]
    SEMANTIC_TAGS = ["slack", "search", "find"]
    TOOL_CATEGORY = "communication"

    def get_tool_name(self) -> str:
        return "slack_search"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        try:
            user_id = str(inputs.get("_user_id") or inputs.get("user_id"))
            client = await get_slack_client(user_id)
            count = int(inputs.get("count", 20))

            matches = await client.search_messages(inputs["query"], count=count)
            result = [{
                "text": m.get("text", ""),
                "channel_name": m.get("channel", {}).get("name", ""),
                "user": m.get("username", ""),
                "timestamp": m.get("ts", ""),
                "permalink": m.get("permalink", ""),
            } for m in matches]

            return ToolOutput(success=True, data={"matches": result, "total": len(result)})
        except Exception as exc:
            return ToolOutput(success=False, data={}, error=str(exc))


__all__ = ["SlackMessagesTool", "SlackSendTool", "SlackSearchTool"]
```

### Step 6.3: Update Google plugin.json

Add calendar tools to the existing google plugin:

```json
{
  "name": "google",
  "version": "1.1.0",
  "display_name": "Google Services",
  "description": "Google service connectors — Gmail, Calendar, Drive.",
  "author": "spark-core",
  "capabilities": [
    "email_read", "email_send", "email_organize", "email_search",
    "calendar_read", "calendar_write"
  ],
  "tools": [
    "email_list", "email_read", "email_send", "email_reply",
    "email_delete", "email_trash", "email_mark_read", "email_mark_unread",
    "email_search", "email_label", "email_move", "email_organize",
    "email_labels_list",
    "calendar_list_events", "calendar_create_event"
  ],
  "skills": [],
  "dependencies": [],
  "requires_oauth": ["gmail", "google_calendar"],
  "config_schema": {},
  "enabled": true
}
```

---

## Phase 7: Token-Saving Tool Injection Strategy

> Goal: Ensure MCP + native tools don't bloat LLM prompts.

### Step 7.1: The rule

**NEVER put all tool schemas in the prompt.** The SQH prompt builder must filter tools before injection.

### Step 7.2: Implement category-based filtering

In your SQH prompt builder (wherever `get_tools_schema()` lives), ensure it filters:

```python
# In the SQH prompt building logic:

def get_tools_for_sqh(intent: str, categories: list[str], connected_services: list[str]) -> list[ToolMetadata]:
    """
    Return ONLY relevant tools for the current SQH call.
    
    Rules:
    1. Only include tools from categories matching the intent
    2. Only include tools for CONNECTED services (no point showing Slack tools if not connected)
    3. Cap at 15 tools max per SQH call
    4. Prefer native tools over MCP tools for the same capability
    """
    from app.plugins.tools.registry_loader import tool_registry

    candidates = []
    
    for tool_name, meta in tool_registry.tools.items():
        # Skip tools for disconnected services
        if meta.category == "external" and meta.metadata.get("server") not in connected_services:
            continue
        if meta.category == "communication" and "gmail" not in connected_services:
            if "email" in tool_name:
                continue

        # Match by category or semantic tags
        if meta.category in categories:
            candidates.append(meta)
        elif any(tag in meta.semantic_tags for tag in categories):
            candidates.append(meta)

    # Sort: native before MCP, then by relevance
    candidates.sort(key=lambda m: (0 if m.metadata.get("source") != "mcp" else 1))

    return candidates[:15]
```

### Step 7.3: Two-pass tool selection (optional optimization)

For maximum token savings, you can do tool selection in two passes:

```
Pass 1 (cheap): Give LLM one-line summaries of 50+ tools → it picks 1-3 names
Pass 2 (focused): Inject full schemas of ONLY the chosen tools → LLM generates params
```

This is optional for now — your category-based filtering already cuts 80 tools down to ~5-10 per call, which is fine.

---

## Phase 8: Frontend Connector Dashboard

> Goal: User sees all services, can connect/disconnect from Spark UI.

### Step 8.1: API contract

The frontend calls:

```
GET /connectors/list?user_id=abc123
→ [
    {id: "gmail", display_name: "Gmail", connected: true, icon: "gmail", ...},
    {id: "slack", display_name: "Slack", connected: false, icon: "slack", ...},
    ...
  ]

# User clicks "Connect" on Slack:
GET /auth/slack/connect?user_id=abc123
→ Redirects to Slack OAuth consent → callback → stored → frontend polls status

# User clicks "Disconnect":
DELETE /auth/slack/disconnect?user_id=abc123
→ Token revoked
```

### Step 8.2: Frontend component structure

```
electron/src/components/settings/
└── ConnectedServices/
    ├── ConnectedServices.tsx       ← main grid
    ├── ServiceCard.tsx             ← single service card (icon, name, status, button)
    └── useConnectorStatus.ts      ← hook that calls /connectors/list
```

The ServiceCard shows:
- Service icon + name
- "Connected" (green) or "Not connected" (gray)
- "Connect" button → opens OAuth popup
- "Disconnect" button → calls DELETE endpoint
- Capabilities list (optional)

---

## Phase 9: Server Startup Integration

> Goal: Wire everything together at server boot.

### Step 9.1: Startup sequence

Add to your FastAPI startup event:

```python
# In app startup (lifespan or @app.on_event("startup")):

async def startup_connectors():
    """Initialize the connector system at server boot."""
    import logging
    logger = logging.getLogger("connectors.startup")

    # 1. Load connector registry (instant — just Python dicts)
    from app.connectors.registry import CONNECTORS
    logger.info("Loaded %d connector definitions", len(CONNECTORS))

    # 2. MCP: pre-warm servers for connected services (background)
    from app.connectors.mcp.manager import get_mcp_manager
    manager = get_mcp_manager()

    # Only spawn MCP servers whose env vars are configured
    for server_name in manager.get_available_servers():
        try:
            tools = await manager.discover_tools(server_name)
            logger.info("MCP '%s': %d tools ready", server_name, len(tools))
        except Exception as e:
            logger.debug("MCP '%s' skipped (not configured): %s", server_name, e)

    # 3. Register MCP tools into the tool registry
    await register_mcp_tools()  # from Phase 5.5

    # 4. Start idle cleanup task
    import asyncio
    asyncio.create_task(_mcp_idle_cleanup_loop())


async def _mcp_idle_cleanup_loop():
    """Periodically kill idle MCP servers."""
    import asyncio
    from app.connectors.mcp.manager import get_mcp_manager
    while True:
        await asyncio.sleep(120)  # check every 2 minutes
        await get_mcp_manager().cleanup_idle()
```

### Step 9.2: Shutdown cleanup

```python
# In app shutdown:
async def shutdown_connectors():
    from app.connectors.mcp.manager import get_mcp_manager
    await get_mcp_manager().shutdown_all()
```

---

## Phase 10: The "Organize My Day" Skill

> Goal: A skill (DAG) that fans out to all connected services and aggregates results.

This comes AFTER the above phases are working. It's a skill that:

1. Checks which services are connected for the user
2. Fans out parallel tool calls to each connected service
3. Aggregates results into a structured daily summary
4. Returns to the LLM for formatting + TTS speech

```python
# server/plugins/installed/spark/tools/organize_day.py
"""'Organize my day' — aggregate data from all connected services."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

from app.connectors.registry import get_all_connector_statuses
from app.plugins.tools.tool_base import BaseTool, ToolOutput

logger = logging.getLogger(__name__)


class OrganizeDayTool(BaseTool):
    """
    Pull today's data from all connected services into one summary.

    Internally calls: email_list, calendar_list_events, slack unread, etc.
    Only calls services the user has actually connected.
    """

    TOOL_DESCRIPTION = "Aggregate today's emails, calendar, tasks, and messages from all connected services"
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA = {
        "user_id": {"type": "string", "required": True},
    }
    OUTPUT_SCHEMA = {
        "success": {"type": "boolean"},
        "data": {"summary": {"type": "object"}},
        "error": {"type": "string"},
    }
    EXAMPLES = [{"user_utterance": "organize my day"}, {"user_utterance": "what do I have today"}]
    SEMANTIC_TAGS = ["organize", "day", "summary", "today", "overview", "morning"]
    TOOL_CATEGORY = "productivity"
    METADATA: Dict[str, Any] = {"summary_tts": True}

    def get_tool_name(self) -> str:
        return "organize_day"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        user_id = str(inputs.get("_user_id") or inputs.get("user_id"))
        if not user_id:
            return ToolOutput(success=False, data={}, error="user_id required")

        # Check what's connected
        statuses = await get_all_connector_statuses(user_id)
        connected = {s["id"] for s in statuses if s["connected"]}

        summary: Dict[str, Any] = {}
        tasks: List[asyncio.Task] = []

        # Fan out to connected services
        if "gmail" in connected:
            tasks.append(asyncio.create_task(self._get_emails(user_id)))
        if "google_calendar" in connected:
            tasks.append(asyncio.create_task(self._get_calendar(user_id)))
        if "slack" in connected:
            tasks.append(asyncio.create_task(self._get_slack(user_id)))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect results
        idx = 0
        if "gmail" in connected:
            if not isinstance(results[idx], Exception):
                summary["email"] = results[idx]
            idx += 1
        if "google_calendar" in connected:
            if not isinstance(results[idx], Exception):
                summary["calendar"] = results[idx]
            idx += 1
        if "slack" in connected:
            if not isinstance(results[idx], Exception):
                summary["slack"] = results[idx]
            idx += 1

        summary["connected_services"] = list(connected)
        return ToolOutput(success=True, data={"summary": summary})

    async def _get_emails(self, user_id: str) -> dict:
        from app.connectors.clients.gmail import get_gmail_service
        service = await get_gmail_service(user_id)
        resp = service.users().messages().list(
            userId="me", labelIds=["INBOX", "UNREAD"], maxResults=5
        ).execute()
        count = resp.get("resultSizeEstimate", 0)
        return {"unread_count": count, "preview": resp.get("messages", [])[:3]}

    async def _get_calendar(self, user_id: str) -> dict:
        from app.connectors.clients.calendar import get_calendar_service
        from datetime import datetime, timedelta
        service = await get_calendar_service(user_id)
        now = datetime.utcnow()
        resp = service.events().list(
            calendarId="primary",
            timeMin=now.isoformat() + "Z",
            timeMax=(now + timedelta(days=1)).isoformat() + "Z",
            maxResults=10, singleEvents=True, orderBy="startTime",
        ).execute()
        events = [{
            "summary": e.get("summary", ""),
            "start": e.get("start", {}).get("dateTime", ""),
        } for e in resp.get("items", [])]
        return {"event_count": len(events), "events": events}

    async def _get_slack(self, user_id: str) -> dict:
        # For Slack, just report that it's connected — detailed fetch would need channel selection
        return {"connected": True, "note": "Slack connected — ask about specific channels"}


__all__ = ["OrganizeDayTool"]
```

---

## Best Practices Checklist

Follow these rules across all connector code:

### Security
- [ ] NEVER store tokens in plaintext — always Fernet-encrypted
- [ ] NEVER log access tokens or refresh tokens (even at DEBUG level)
- [ ] ALWAYS validate `user_id` before any token operation
- [ ] ALWAYS check `is_connected()` before attempting API calls
- [ ] Handle `invalid_grant` (token revoked externally) gracefully

### Performance
- [ ] Cache service clients (50 min TTL) — don't rebuild on every call
- [ ] Cache access tokens (59 min TTL) — don't refresh on every call
- [ ] MCP servers: lazy-spawn, kill when idle (10 min timeout)
- [ ] Never inject all tool schemas into LLM prompts — filter by category/intent
- [ ] Use `asyncio.gather()` for parallel fan-out (organize_day pattern)

### Scalability
- [ ] Adding a new OAuth service = 1 entry in `providers.py` + 1 client in `clients/`
- [ ] Adding a new MCP service = 1 entry in `servers.json` (zero code)
- [ ] All tools use the same `BaseTool` interface regardless of source
- [ ] Registry is the single source of truth for "what can Spark connect to"

### User Experience
- [ ] Frontend shows all available connectors with connect/disconnect buttons
- [ ] Connected status is real-time (poll or WebSocket update)
- [ ] Clear error messages when a service is disconnected mid-use
- [ ] User can revoke any service at any time — one click disconnect

### Token Efficiency
- [ ] SQH only receives tool schemas for relevant + connected services
- [ ] Category-based filtering reduces 80 tools → 5-10 per prompt
- [ ] MCP tool schemas are cached after first `tools/list` (not re-fetched)
- [ ] Two-pass selection (summaries → full schema) for 50+ tool scenarios

---

## Implementation Order (Priority)

```
Week 1: Phase 1 (migration) + Phase 2 (registry)
         → Clean structure, nothing breaks, frontend has an API

Week 2: Phase 3 (new OAuth providers) + Phase 4 (clients)
         → Calendar + Drive + Slack OAuth working

Week 3: Phase 6 (tool plugins)
         → Calendar and Slack tools callable by Spark

Week 4: Phase 5 (MCP) + Phase 7 (token optimization)
         → Notion/GitHub via MCP, prompts stay lean

Week 5: Phase 8 (frontend) + Phase 9 (startup) + Phase 10 (organize_day)
         → Full end-to-end "organize my day" working
```

---

## Testing Each Phase

After each phase, verify:

```bash
# Phase 1: Old imports still work via shims
python -c "from app.connectors.oauth import is_connected; print('OK')"

# Phase 2: Registry responds
curl http://localhost:8000/connectors/list?user_id=test

# Phase 3: OAuth flow works
# Open browser: http://localhost:8000/auth/google_calendar/connect?user_id=test

# Phase 4: Clients build
python -c "import asyncio; from app.connectors.clients.calendar import get_calendar_service; print('OK')"

# Phase 5: MCP spawns
python -c "import asyncio; from app.connectors.mcp.manager import get_mcp_manager; m = get_mcp_manager(); print(m.get_available_servers())"

# Phase 6: Tools execute
# Via Spark: "what's on my calendar today?" → should return events

# Full E2E:
# "Spark, organize my day" → pulls from all connected services
```

---

## Files to Delete After Full Migration

Once everything is working and tested:

```
DELETE: server/app/features/external_service/    (entire dir)
DELETE: server/app/features/bridge/              (entire dir)
DELETE: server/app/features/gmail/               (entire dir)
DELETE: server/shared/service_client.py
DELETE: server/plugins/installed/google/tools/gmail_bridge.py
DELETE: server/CONNECTOR_ARCHITECTURE.md         (replaced by this guide)
```
