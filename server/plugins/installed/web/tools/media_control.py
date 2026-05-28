"""media_control — operate the currently-playing media tab in place.

Why it's separate from browser_action
─────────────────────────────────────
``browser_action`` (play_media) *navigates* — it spawns a flow that
searches, picks a result, and lands on /watch. That's expensive.
Once the video is playing, follow-up utterances like "pause", "next
song", "skip the ad" should NOT re-run the flow. They should reach
into the live YouTube tab and execute a single JS command.

This tool does exactly that: takes a control verb, grabs the existing
YouTube tab from the persistent ``BrowserSession`` (no reconnect, no
navigation), and runs the matching JS. If no YouTube tab is open it
fails fast with a clear "no_tab" reason — it's the user's job to play
something first.

Supported controls
──────────────────
  pause / play / toggle      — play state
  next / previous            — autoplay queue navigation (uses
                                 ``.ytp-next-button`` / ``.ytp-prev-button``)
  skip_ad                    — clicks the skip-ad button when visible
  mute / unmute              — mute state
  volume        (level 0..1) — exact volume
  volume_up / volume_down    — ±10%
  seek_forward / seek_back   — ±10s by default; ``seconds`` overrides
  fullscreen / exit_fullscreen
  status                     — return current player state (no change)

Future controls map to one more JS snippet each.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from app.plugins.tools.tool_base import BaseTool, ToolOutput
from ..browser.session import get_browser_session

logger = logging.getLogger(__name__)

YOUTUBE_HOST = "youtube.com"


# ── JS snippets ──────────────────────────────────────────────────────────────
# Each snippet must return a small JSON-able dict so callers can verify what
# happened. Keep them tiny — the browser is the source of truth, we just nudge it.

_STATUS_JS = """
() => {
    const v = document.querySelector('video');
    if (!v) return {ok: false, reason: 'no video element'};
    return {
        ok: true,
        paused: v.paused,
        muted: v.muted,
        volume: v.volume,
        currentTime: v.currentTime,
        duration: v.duration,
        ended: v.ended,
        playbackRate: v.playbackRate,
    };
}
"""

_PAUSE_JS = "() => { const v=document.querySelector('video'); if(!v) return {ok:false,reason:'no video'}; v.pause(); return {ok:true, paused:v.paused}; }"
_PLAY_JS  = "() => { const v=document.querySelector('video'); if(!v) return {ok:false,reason:'no video'}; v.play(); return {ok:true, paused:v.paused}; }"
_TOGGLE_JS = "() => { const v=document.querySelector('video'); if(!v) return {ok:false,reason:'no video'}; v.paused?v.play():v.pause(); return {ok:true, paused:v.paused}; }"

_MUTE_JS   = "() => { const v=document.querySelector('video'); if(!v) return {ok:false,reason:'no video'}; v.muted=true;  return {ok:true, muted:v.muted}; }"
_UNMUTE_JS = "() => { const v=document.querySelector('video'); if(!v) return {ok:false,reason:'no video'}; v.muted=false; return {ok:true, muted:v.muted}; }"

# The autoplay nav buttons on YouTube. We click via .click() rather than
# Playwright's locator because the element is sometimes off-screen / hidden
# behind overlays, and .click() in DOM bypasses those checks.
_NEXT_JS = """
() => {
    const btn = document.querySelector('.ytp-next-button');
    if (!btn) return {ok: false, reason: 'no next button'};
    btn.click();
    return {ok: true};
}
"""
_PREV_JS = """
() => {
    const btn = document.querySelector('.ytp-prev-button');
    if (!btn) return {ok: false, reason: 'no previous button'};
    btn.click();
    return {ok: true};
}
"""

# Skip-ad class name varies (.ytp-ad-skip-button, .ytp-ad-skip-button-modern,
# .ytp-skip-ad-button). Try them all.
_SKIP_AD_JS = """
() => {
    const sel = [
        '.ytp-ad-skip-button',
        '.ytp-ad-skip-button-modern',
        '.ytp-skip-ad-button',
        'button.ytp-ad-skip-button-modern',
    ];
    for (const s of sel) {
        const b = document.querySelector(s);
        if (b) { b.click(); return {ok: true, used: s}; }
    }
    return {ok: false, reason: 'no skip button visible (no ad, or not skippable yet)'};
}
"""

_FULLSCREEN_JS = """
() => {
    const btn = document.querySelector('.ytp-fullscreen-button');
    if (!btn) return {ok: false, reason: 'no fullscreen button'};
    btn.click();
    return {ok: true};
}
"""


def _set_volume_js(level: float) -> str:
    # Clamp on the JS side too — JS Number coercion can do weird things.
    return f"""
    () => {{
        const v = document.querySelector('video');
        if (!v) return {{ok:false, reason:'no video'}};
        const lvl = Math.max(0, Math.min(1, {level}));
        v.volume = lvl;
        v.muted = lvl === 0;
        return {{ok:true, volume:v.volume, muted:v.muted}};
    }}
    """


def _bump_volume_js(delta: float) -> str:
    return f"""
    () => {{
        const v = document.querySelector('video');
        if (!v) return {{ok:false, reason:'no video'}};
        const lvl = Math.max(0, Math.min(1, v.volume + ({delta})));
        v.volume = lvl;
        if (lvl > 0) v.muted = false;
        return {{ok:true, volume:v.volume, muted:v.muted}};
    }}
    """


def _seek_js(delta_s: float) -> str:
    return f"""
    () => {{
        const v = document.querySelector('video');
        if (!v) return {{ok:false, reason:'no video'}};
        const dur = isFinite(v.duration) ? v.duration : Number.MAX_SAFE_INTEGER;
        v.currentTime = Math.max(0, Math.min(dur, v.currentTime + ({delta_s})));
        return {{ok:true, currentTime:v.currentTime}};
    }}
    """


# ── Action registry ─────────────────────────────────────────────────────────
# Each handler returns the dict that goes into ToolOutput.data.

_Handler = Callable[[Any, Dict[str, Any]], Awaitable[Dict[str, Any]]]


async def _run(page: Any, js: str) -> Dict[str, Any]:
    """Run a JS snippet on the page and normalize the dict result."""
    res = await page.evaluate(js)
    if not isinstance(res, dict):
        return {"ok": False, "reason": f"unexpected JS result type: {type(res).__name__}"}
    return res


async def _h_status(page: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    return await _run(page, _STATUS_JS)

async def _h_pause(page: Any, params): return await _run(page, _PAUSE_JS)
async def _h_play(page: Any, params):  return await _run(page, _PLAY_JS)
async def _h_toggle(page: Any, params): return await _run(page, _TOGGLE_JS)
async def _h_mute(page: Any, params):  return await _run(page, _MUTE_JS)
async def _h_unmute(page: Any, params): return await _run(page, _UNMUTE_JS)
async def _h_next(page: Any, params):  return await _run(page, _NEXT_JS)
async def _h_prev(page: Any, params):  return await _run(page, _PREV_JS)
async def _h_skip_ad(page: Any, params): return await _run(page, _SKIP_AD_JS)
async def _h_fullscreen(page: Any, params): return await _run(page, _FULLSCREEN_JS)


async def _h_volume(page: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    level = params.get("level")
    if level is None:
        return {"ok": False, "reason": "control=volume requires `level` (0.0..1.0)"}
    return await _run(page, _set_volume_js(float(level)))


async def _h_volume_up(page: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    return await _run(page, _bump_volume_js(0.1))


async def _h_volume_down(page: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    return await _run(page, _bump_volume_js(-0.1))


async def _h_seek_forward(page: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    seconds = float(params.get("seconds", 10))
    return await _run(page, _seek_js(abs(seconds)))


async def _h_seek_back(page: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    seconds = float(params.get("seconds", 10))
    return await _run(page, _seek_js(-abs(seconds)))


_HANDLERS: Dict[str, _Handler] = {
    "status":          _h_status,
    "pause":           _h_pause,
    "play":            _h_play,
    "toggle":          _h_toggle,
    "mute":            _h_mute,
    "unmute":          _h_unmute,
    "next":            _h_next,
    "previous":        _h_prev,
    "skip_ad":         _h_skip_ad,
    "fullscreen":      _h_fullscreen,
    "exit_fullscreen": _h_fullscreen,  # same toggle button
    "volume":          _h_volume,
    "volume_up":       _h_volume_up,
    "volume_down":     _h_volume_down,
    "seek_forward":    _h_seek_forward,
    "seek_back":       _h_seek_back,
}


# ── Tool ─────────────────────────────────────────────────────────────────────

class MediaControlTool(BaseTool):
    """Control the currently-playing media tab in place.

    Use this for follow-up commands after ``browser_action play_media``:
    pause / play / next / skip ad / volume / etc. Does not navigate —
    fails fast if no YouTube tab is open.
    """

    TOOL_DESCRIPTION = (
        "Control the currently-playing video tab in place: pause, play, "
        "toggle, next, previous, skip ad, mute, volume, seek, fullscreen, "
        "status. Use after a video is already playing (browser_action "
        "play_media). Does not search or navigate."
    )
    EXECUTION_TARGET = "server"
    PARAMS_SCHEMA: Dict[str, Any] = {
        "control": {
            "type": "string",
            "required": True,
            "enum": list(_HANDLERS.keys()),
            "description": (
                "pause | play | toggle | next | previous | skip_ad | "
                "mute | unmute | volume | volume_up | volume_down | "
                "seek_forward | seek_back | fullscreen | exit_fullscreen | status"
            ),
        },
        "level": {
            "type": "number",
            "required": False,
            "description": "For control=volume: target level 0.0..1.0",
        },
        "seconds": {
            "type": "number",
            "required": False,
            "description": "For seek_forward / seek_back: seconds to skip (default 10).",
        },
    }
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "success": {"type": "boolean"},
        "data": {
            "control":   {"type": "string"},
            "ok":        {"type": "boolean"},
            "reason":    {"type": "string", "optional": True},
        },
        "error": {"type": "string"},
    }
    EXAMPLES = [
        {"user_utterance": "pause"},
        {"user_utterance": "next song"},
        {"user_utterance": "skip the ad"},
        {"user_utterance": "turn the volume down"},
        {"user_utterance": "skip forward 30 seconds"},
    ]
    SEMANTIC_TAGS = ["media", "control", "youtube", "pause", "play", "next", "volume", "skip"]
    TOOL_CATEGORY = "browser_action"

    def get_tool_name(self) -> str:
        return "media_control"

    async def _execute(self, inputs: Dict[str, Any]) -> ToolOutput:
        control = str(self.get_input(inputs, "control", "") or "").strip().lower()
        if not control:
            return ToolOutput(success=False, data={}, error="`control` is required")

        handler = _HANDLERS.get(control)
        if handler is None:
            return ToolOutput(
                success=False,
                data={},
                error=f"Unknown control {control!r}. Valid: {sorted(_HANDLERS)}",
            )

        # Pull params straight through; handlers validate per-control.
        params: Dict[str, Any] = {}
        if (v := self.get_input(inputs, "level", None)) is not None:
            params["level"] = v
        if (v := self.get_input(inputs, "seconds", None)) is not None:
            params["seconds"] = v

        session = get_browser_session()
        try:
            page = await session.get_page(YOUTUBE_HOST, focus=False)
        except Exception as e:
            logger.exception("media_control: failed to acquire YouTube tab")
            return ToolOutput(
                success=False,
                data={"control": control},
                error=f"could not get YouTube tab: {e}",
            )

        # If the chosen tab isn't actually on YouTube, refuse — we never want
        # to call play()/pause() on an unrelated tab the user happens to be on.
        url = (page.url or "").lower()
        if YOUTUBE_HOST not in url:
            return ToolOutput(
                success=False,
                data={"control": control, "url": page.url},
                error=(
                    f"no YouTube tab open (current URL: {page.url!r}). "
                    "Start playback with browser_action play_media first."
                ),
            )

        try:
            result = await handler(page, params)
        except Exception as e:
            logger.exception("media_control: handler %s crashed", control)
            return ToolOutput(success=False, data={"control": control}, error=str(e))

        ok = bool(result.get("ok"))
        return ToolOutput(
            success=ok,
            data={"control": control, **result},
            error=(result.get("reason") if not ok else None),
        )


__all__ = ["MediaControlTool"]
