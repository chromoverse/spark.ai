"""
Provider registry — one dict per external OAuth service.

To add a new service, just append a new entry.  Zero changes needed in
oauth_token_service, token_manager, or the router.

Env vars referenced here must exist in your .env at runtime.
"""

import os
from typing import Dict, Any


# ── Provider configs ────────────────────────────────────────────────────────────

PROVIDERS: Dict[str, Dict[str, Any]] = {
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
    # ── future ──────────────────────────────────────────────────────────────
    # "slack": {
    #     "display_name": "Slack",
    #     "scopes": ["chat:write", "channels:read"],
    #     "auth_uri": "https://slack.com/oauth/v2/authorize",
    #     "token_uri": "https://slack.com/api/oauth.v2.access",
    #     "userinfo_uri": None,
    #     "client_id_env": "SLACK_CLIENT_ID",
    #     "client_secret_env": "SLACK_CLIENT_SECRET",
    #     "redirect_uri_env": "SLACK_REDIRECT_URI",
    #     "default_redirect_uri": "http://localhost:8000/auth/slack/callback",
    # },
}


# ── Helpers ─────────────────────────────────────────────────────────────────────

def get_provider(service: str) -> Dict[str, Any]:
    """Return the config dict for a registered provider, or raise."""
    if service not in PROVIDERS:
        raise ValueError(
            f"Unknown service '{service}'. "
            f"Registered providers: {list(PROVIDERS.keys())}"
        )
    return PROVIDERS[service]


def get_client_id(service: str) -> str:
    return os.getenv(get_provider(service)["client_id_env"], "")


def get_client_secret(service: str) -> str:
    return os.getenv(get_provider(service)["client_secret_env"], "")


def get_redirect_uri(service: str) -> str:
    cfg = get_provider(service)
    return os.getenv(cfg["redirect_uri_env"], cfg["default_redirect_uri"])
