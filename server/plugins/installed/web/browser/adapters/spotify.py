"""Spotify Web Player adapter.

Goal: ``spotify_play`` intent — "play <something> on Spotify". Behaves
like the YouTube adapter, with one important difference: Spotify requires
login. We delegate that to the generic auth helper, which only prompts
the human once per browser profile.

Flow
────
INIT  — ensure_signed_in(spotify_spec); navigate to home.
SEARCH — goto /search/<query>, wait for results.
SELECT — click the first track's play button (or the album/playlist).
VERIFY — verify a track is playing (DOM marker + audio element).

We could go deeper (queue management, like/save, play-from-history) but
that's the same pattern as media_control: those are in-place ops on the
existing tab and belong in a follow-up control tool, not in this flow.
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

from .base import SiteAdapter, SiteCapabilities
from ..action_graph import ActionGraph, ActionStep, StepContext
from ..auth import AuthSpec, ensure_signed_in
from ..errors import BrowserError, BrowserErrorType
from ..semantic import ActionResult, goto, wait_navigation
from ..state_machine import FlowState
from ..verification import GoalVerifier

logger = logging.getLogger(__name__)


# ── Auth spec ──────────────────────────────────────────────────────────────

SPOTIFY_AUTH = AuthSpec(
    name="spotify",
    home_url="https://open.spotify.com/",
    login_url="https://accounts.spotify.com/en/login",
    # Spotify Web Player puts the user avatar / button in a data-testid'd
    # element when signed in.
    signed_in_selector='[data-testid="user-widget-link"], [data-testid="user-widget-avatar"]',
    # When signed out the top bar shows "Log in" + "Sign up" buttons.
    signed_out_selectors=(
        '[data-testid="login-button"]',
        'button:has-text("Log in")',
    ),
    cookie_indicators=("sp_dc", "sp_key"),  # standard Spotify session cookies
)


# ── Steps ──────────────────────────────────────────────────────────────────

def _spotify_search_url(query: str) -> str:
    """Spotify Web Player honors /search/<query> as a deep link."""
    return f"https://open.spotify.com/search/{quote(query)}"


def goto_spotify_search(query: str) -> ActionStep:
    """Navigate the existing tab straight to Spotify's search results page."""
    async def run(ctx: StepContext):
        result = await goto(ctx.page, _spotify_search_url(query), ctx.runtime)
        # Spotify's search SPA needs a moment after navigation completes
        # before the results list is fully rendered.
        try:
            await ctx.page.wait_for_selector(
                '[data-testid="search-tracks-result"], [data-testid="tracklist-row"]',
                timeout=8_000,
            )
        except Exception:
            # The selector wait failing isn't fatal — the subsequent
            # click step will report its own error if results never came.
            pass
        return result

    return ActionStep(
        name="goto_spotify_search",
        goal=f"Navigate to Spotify search for {query!r}",
        run=run,
    )


def click_first_track_play() -> ActionStep:
    """Click the first visible play button on the search-results page.

    Spotify's DOM changes often — class names, testids, even container
    structure. Across every version since 2022, though, ONE thing has
    been stable: play controls expose ``data-testid="play-button"``.
    So instead of matching a tracklist row first and digging inside,
    we just take the first such button on the page.

    On the search page that first play button is reliably the top
    result card's "play this artist/track/album" button — which is the
    most relevant thing for a "play X on spotify" intent anyway. If
    Spotify ships a global header play button later, we'll revisit.

    Strategy ladder:
      1. ``[data-testid="play-button"]:visible`` → first one.
      2. Fallback to ``button[aria-label^="Play"]:visible`` in case
         Spotify ever drops the testid.
    """
    async def run(ctx: StepContext):
        page = ctx.page

        # Strategy 1: stable data-testid.
        try:
            btn = page.locator('[data-testid="play-button"]').first
            await btn.wait_for(state="visible", timeout=10_000)
            await btn.scroll_into_view_if_needed(timeout=3_000)
            await btn.click(timeout=5_000, force=True)
            return ActionResult(
                ok=True, action="click_first_track_play",
                target='data-testid="play-button"', confidence=0.95,
                evidence={"strategy": "play_button_testid"},
            )
        except Exception as e:
            logger.debug("spotify: data-testid play-button not found: %s", e)

        # Strategy 2: aria-label fallback. CSS attribute prefix match —
        # survives most DOM reshuffles because it's semantic, not
        # class-based, and Playwright's CSS supports `[attr^=...]`.
        try:
            btn = page.locator('button[aria-label^="Play"]').first
            await btn.wait_for(state="visible", timeout=5_000)
            await btn.scroll_into_view_if_needed(timeout=3_000)
            await btn.click(timeout=5_000, force=True)
            return ActionResult(
                ok=True, action="click_first_track_play",
                target='aria-label^="Play"', confidence=0.85,
                evidence={"strategy": "aria_label_fallback"},
            )
        except Exception as e:
            return ActionResult(
                ok=False, action="click_first_track_play",
                target="play button", confidence=0.0,
                error_type=BrowserErrorType.ELEMENT_NOT_FOUND,
                error_detail=(
                    "no Spotify play button found via "
                    f'data-testid="play-button" or aria-label="Play …": {e}'
                ),
            )

    return ActionStep(
        name="click_first_track_play",
        goal="Click play on the first Spotify search result",
        run=run,
    )


# ── Adapter ────────────────────────────────────────────────────────────────

class SpotifyAdapter(SiteAdapter):
    """Spotify Web Player play adapter."""

    name = "spotify"
    base_url = "https://open.spotify.com"
    capabilities = SiteCapabilities(
        supports_checkout=False,
        requires_login=True,
        high_bot_detection=False,
        supports_autofill=False,
        supports_dry_run=True,
    )

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def do_init(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        """Make sure the user is signed in before we try to play anything.

        On sign-in timeout we raise a typed BrowserError — the Flow's
        top-level handler catches it and aborts cleanly. We can't return
        next_state=ABORTED here because INIT->ABORTED is not a legal
        transition in the state machine; raising is the contracted way.
        """
        ok = await ensure_signed_in(page, SPOTIFY_AUTH, runtime, timeout_s=120.0)
        if not ok:
            raise BrowserError(
                BrowserErrorType.LOGIN_REQUIRED,
                "Spotify sign-in not completed within 2 minutes",
                page.url,
            )
        ctx["spotify_init"] = True
        return type("Result", (), {
            "next_state": FlowState.SEARCH, "confidence": 1.0,
        })()

    async def do_search(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        graph = ActionGraph([
            goto_spotify_search(intent),
        ])
        step_ctx = StepContext(page, intent, ctx, runtime)
        result = await graph.execute(step_ctx)
        ctx["spotify_search"] = True
        return type("Result", (), {
            "next_state": FlowState.SELECT,
            "confidence": getattr(result, "confidence", 0.9),
        })()

    async def do_select(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        """Click the first play button on the search results.

        On failure we raise BrowserError rather than returning
        next_state=ABORTED, because SELECT->ABORTED is not a legal
        transition. The Flow catches the exception in its top-level
        handler and aborts with the typed error attached.
        """
        graph = ActionGraph([
            click_first_track_play(),
        ])
        step_ctx = StepContext(page, intent, ctx, runtime)
        result = await graph.execute(step_ctx)
        ctx["spotify_select"] = True
        if not getattr(result, "ok", True):
            raise BrowserError(
                getattr(result, "error_type", None) or BrowserErrorType.ELEMENT_NOT_FOUND,
                getattr(result, "error_detail", None) or "Could not click any Spotify play button",
                page.url,
            )
        return type("Result", (), {
            "next_state": FlowState.VERIFYING,
            "confidence": getattr(result, "confidence", 0.9),
        })()

    # The rest of the lifecycle hooks aren't used for "play" flows.
    async def do_form_fill(self, page, intent, ctx, runtime):
        return type("Result", (), {"next_state": FlowState.VERIFYING, "confidence": 1.0})()

    async def do_review(self, page, intent, ctx, runtime):
        return type("Result", (), {"next_state": FlowState.VERIFYING, "confidence": 1.0})()

    async def do_user_confirm(self, page, intent, ctx, runtime):
        return type("Result", (), {"next_state": FlowState.VERIFYING, "confidence": 1.0})()

    # ── Verification ──────────────────────────────────────────────────────

    async def verify_goal_completed(self, page: Any, intent: str, ctx: dict, runtime: Any) -> Any:
        """Confirm something is actually playing.

        Two signals:
          1. Now-playing widget has a track name (the bar at the bottom).
          2. The page has a non-paused HTMLAudioElement / HTMLMediaElement.

        Either alone is enough; both is best.
        """
        if not self.verifier:
            self.verifier = GoalVerifier()

        now_playing = False
        try:
            count = await page.locator(
                '[data-testid="now-playing-widget"] [data-testid="context-item-link"], '
                '[data-testid="now-playing-widget"] a[data-testid="context-item-link"]'
            ).count()
            now_playing = count > 0
        except Exception as e:
            logger.debug("spotify verify: now-playing check failed: %s", e)

        # Spotify uses HTMLAudioElement, not <video>; check media elements.
        media_playing = False
        try:
            media_playing = bool(await page.evaluate(
                """
                () => {
                    const els = [...document.querySelectorAll('audio,video')];
                    return els.some(e => !e.paused && !e.ended && e.currentTime > 0);
                }
                """
            ))
        except Exception as e:
            logger.debug("spotify verify: media element check failed: %s", e)

        if media_playing and now_playing:
            return type("Result", (), {"next_state": FlowState.DONE, "confidence": 1.0})()
        if media_playing or now_playing:
            # One signal — still pass, but lower confidence. Spotify's
            # audio element can briefly read paused=true between tracks.
            return type("Result", (), {"next_state": FlowState.DONE, "confidence": 0.8})()
        return type("Result", (), {"next_state": FlowState.ABORTED, "confidence": 0.0})()
