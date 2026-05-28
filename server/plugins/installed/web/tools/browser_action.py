"""
browser_action — transactional browser tool.

This tool exists because retrieval and action belong to *different*
subsystems (per the retrieval-architecture guide). ``web_research`` finds
entities; ``browser_action`` does something *with* them — book a room,
buy a product, play a movie. It must never be used to search.

Contract
────────
Always takes a verb (``action``) plus either a structured entity (the
exact dict returned by ``web_research``) or an explicit URL / title.
Never a freeform query.

Shipped handlers
────────────────
  open_url        → opens entity.booking_url / entity.maps_url / website /
                    the explicit ``url`` arg in the user's default browser.
                    Honest minimal handler — works today on every site.

  play_media      → opens a YouTube search for ``title`` (or the entity
                    name). Real automation later if the user wants
                    auto-play / Netflix etc.

Stubbed handlers (return graceful "opening URL for manual completion")
  book_hotel      → opens the hotel's booking_url; user finishes the flow.
  buy_product     → opens the product's buy_url.
  reserve_table   → opens the restaurant's booking_url / Google Maps.
  book_ticket     → opens the event's booking_url.

Real automation (Playwright/nodriver flows with auth) will replace these
stubs as we add per-site adapters. The contract above doesn't change —
upgrading a handler just means swapping its body.

Execution
─────────
Runs on the server (the desktop user's machine in DESKTOP mode). Uses
``webbrowser.open`` via ``asyncio.to_thread`` so the OS-level browser
launch never blocks the event loop.
"""

from __future__ import annotations

import asyncio
import logging
import webbrowser
from typing import Any, Awaitable, Callable, Dict, Optional
from urllib.parse import quote_plus

from app.plugins.tools.tool_base import BaseTool, ToolOutput

logger = logging.getLogger(__name__)


# ── Action registry ──────────────────────────────────────────────────────────
# Mapping action verb → async handler. Adding a new action = one entry.
# Each handler takes the resolved ``BrowserActionContext`` and returns the
# data dict that will surface in ToolOutput.

class BrowserActionContext:
    """Normalized inputs the handlers consume."""
    __slots__ = ("action", "entity", "url", "title", "params")

    def __init__(
        self,
        action: str,
        entity: Optional[Dict[str, Any]],
        url: Optional[str],
        title: Optional[str],
        params: Dict[str, Any],
    ) -> None:
        self.action = action
        self.entity = entity or {}
        self.url = url
        self.title = title
        self.params = params or {}


_Handler = Callable[[BrowserActionContext], Awaitable[Dict[str, Any]]]


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _open_browser(url: str) -> bool:
    """Launch the OS default browser pointed at ``url``. Non-blocking."""
    try:
        return bool(await asyncio.to_thread(webbrowser.open, url))
    except Exception as exc:
        logger.warning("browser_action: webbrowser.open(%r) failed: %s", url, exc)
        return False


def _entity_url(entity: Dict[str, Any], *, prefer: tuple = ("booking_url", "maps_url", "website", "buy_url", "menu_url", "source_url")) -> Optional[str]:
    """Pull the most useful URL off an entity for this action."""
    for key in prefer:
        v = entity.get(key)
        if v and isinstance(v, str):
            return v
    return None


def _maps_search_url(name: str, address: Optional[str] = None) -> str:
    parts = [p for p in (name, address) if p]
    q = quote_plus(", ".join(parts))
    return f"https://www.google.com/maps/search/?api=1&query={q}"


def _youtube_search_url(title: str) -> str:
    return f"https://www.youtube.com/results?search_query={quote_plus(title)}"


# ── Handlers ─────────────────────────────────────────────────────────────────

async def _handle_open_url(ctx: BrowserActionContext) -> Dict[str, Any]:
    """Open whatever URL the entity / ctx exposes. Generic 'do something' button."""
    url = ctx.url or _entity_url(ctx.entity) or (
        _maps_search_url(ctx.entity.get("name", ""), ctx.entity.get("address"))
        if ctx.entity.get("name") else None
    )
    if not url:
        return {"opened": False, "reason": "no URL on entity and none provided"}
    ok = await _open_browser(url)
    return {
        "opened": ok,
        "url": url,
        "action": "open_url",
        "message": f"Opened {url}" if ok else "Browser launch failed",
    }


async def _handle_play_media(ctx: BrowserActionContext) -> Dict[str, Any]:
    """Delegate to BrowserAgentTool if available, else fallback to URL open."""
    title = ctx.title or ctx.entity.get("name") or ctx.entity.get("title")
    if not title:
        return {"opened": False, "reason": "no title or entity name to play"}
    
    # Try automated flow first
    try:
        from ..browser.tool import BrowserAgentTool
        tool = BrowserAgentTool()
        result = await tool._execute({
            "intent": "youtube_play",
            "query": str(title),
            "dry_run": False
        })
        if result.success:
            return {
                "opened": True,
                "automated": True,
                "action": "play_media",
                "title": str(title),
                "message": f"Automated YouTube play for {title!r}",
                "data": result.data
            }
    except Exception as e:
        logger.warning("BrowserAgentTool failed, falling back to URL open: %s", e)
    
    # Fallback to URL open
    url = ctx.url or _youtube_search_url(str(title))
    ok = await _open_browser(url)
    return {
        "opened": ok,
        "url": url,
        "action": "play_media",
        "title": str(title),
        "automated": False,
        "message": f"Opened YouTube for {title!r}" if ok else "Browser launch failed",
    }


async def _handle_stub_booking(ctx: BrowserActionContext) -> Dict[str, Any]:
    """Stub for book_hotel / buy_product / reserve_table / book_ticket.

    Opens whatever booking URL the entity exposes so the user can
    complete the flow manually. Real automation comes later.
    """
    url = ctx.url or _entity_url(ctx.entity) or (
        _maps_search_url(ctx.entity.get("name", ""), ctx.entity.get("address"))
        if ctx.entity.get("name") else None
    )
    if not url:
        return {
            "opened": False,
            "automated": False,
            "action": ctx.action,
            "reason": (
                f"{ctx.action}: no booking URL on entity. Pass `url` explicitly or "
                "retrieve the entity again so the provider can fill it in."
            ),
        }
    ok = await _open_browser(url)
    return {
        "opened": ok,
        "automated": False,  # explicit: this is open-and-let-user-finish
        "url": url,
        "action": ctx.action,
        "message": (
            f"Opened {url} for manual completion. "
            f"Automated {ctx.action} flow not yet implemented — the user finishes the flow."
        ),
    }


_HANDLERS: Dict[str, _Handler] = {
    "open_url":      _handle_open_url,
    "play_media":    _handle_play_media,
    # Stubs sharing one impl — distinct action names so future per-flow
    # automation can override them individually without touching callers.
    "book_hotel":    _handle_stub_booking,
    "buy_product":   _handle_stub_booking,
    "reserve_table": _handle_stub_booking,
    "book_ticket":   _handle_stub_booking,
}


# ── Tool ─────────────────────────────────────────────────────────────────────

class BrowserActionTool(BaseTool):
    """Perform a transactional action in the user's browser.

    Use cases:
      • Open a booking page for a hotel/restaurant returned by web_research
      • Play a movie / video by title
      • (Future) Drive an authenticated booking flow end-to-end

    Never use this to *find* things — that's web_research's job.
    """

    TOOL_DESCRIPTION = (
        "Perform a transactional action in the user's browser: open a booking "
        "page, buy a product, reserve a table, play a movie/video. Takes a "
        "verb (action) plus a structured entity (from web_research) or an "
        "explicit URL/title. Not a search tool — use web_research first."
    )
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA: Dict[str, Any] = {
        "action": {
            "type": "string",
            "required": True,
            "enum": list(_HANDLERS.keys()),
            "description": (
                "open_url | play_media | book_hotel | buy_product | "
                "reserve_table | book_ticket"
            ),
        },
        "entity": {
            "type": "object",
            "required": False,
            "description": (
                "Structured entity from web_research (hotel, restaurant, "
                "movie, …). Provides the URL(s) and metadata the action needs."
            ),
        },
        "url": {
            "type": "string",
            "required": False,
            "description": "Explicit URL override. Wins over anything on the entity.",
        },
        "title": {
            "type": "string",
            "required": False,
            "description": "For play_media: title to search for if no entity is given.",
        },
        "params": {
            "type": "object",
            "required": False,
            "description": "Action-specific options (dates, quantity, etc.). Reserved for future automated flows.",
        },
    }
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {
            "action":    {"type": "string"},
            "opened":    {"type": "boolean"},
            "url":       {"type": "string", "optional": True},
            "title":     {"type": "string", "optional": True},
            "automated": {"type": "boolean", "optional": True},
            "message":   {"type": "string", "optional": True},
            "reason":    {"type": "string", "optional": True},
        },
        "error": {"type": "string"},
    }
    EXAMPLES = [
        {"user_utterance": "book that hotel"},
        {"user_utterance": "play interstellar"},
    ]
    SEMANTIC_TAGS = ["browser", "action", "book", "buy", "play", "open"]
    TOOL_CATEGORY = "browser_action"

    def get_tool_name(self) -> str:
        return "browser_action"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        action = str(self.get_input(inputs, "action", "") or "").strip().lower()
        if not action:
            return ToolOutput(success=False, data={}, error="`action` is required")
        handler = _HANDLERS.get(action)
        if handler is None:
            return ToolOutput(
                success=False, data={},
                error=f"Unknown action {action!r}. Valid: {sorted(_HANDLERS)}",
            )

        ctx = BrowserActionContext(
            action=action,
            entity=self.get_input(inputs, "entity", None),
            url=self.get_input(inputs, "url", None),
            title=self.get_input(inputs, "title", None),
            params=self.get_input(inputs, "params", {}) or {},
        )

        try:
            result = await handler(ctx)
        except Exception as exc:
            logger.exception("browser_action: handler %s crashed", action)
            return ToolOutput(success=False, data={"action": action}, error=str(exc))

        # ``opened: false`` is still a "successful" tool call from the
        # orchestrator's perspective — the tool did its job and reported
        # honestly. Only handler crashes / missing inputs are failures.
        return ToolOutput(success=True, data=result)


__all__ = ["BrowserActionTool"]
