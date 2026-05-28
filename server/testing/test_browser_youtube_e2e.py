"""End-to-end test: invoke the browser tool to play a YouTube video.

This is the *flow* test the plan describes ("play lofi beats on youtube"
→ video plays, verify_goal_completed true, DONE). It goes through the
user-facing path (BrowserActionTool → browser_action.play_media →
BrowserAgentTool → YouTubeAdapter → Flow → Playwright → real browser).

Unlike the layer demo scripts, this one:
  - has hard assertions, so it actually fails when something breaks
  - auto-starts Chrome on :9222 if it isn't already running
  - captures the event bus to verify the right lifecycle events fired
  - reads the page DOM at the end to confirm a video element is present
  - never asserts PAYMENT_PAGE_REACHED, since play_media must never hit it

Prerequisites:
    pip install playwright && python -m playwright install chromium
    (Chrome installed; this script will start it with --remote-debugging-port=9222)

Usage:
    python server/testing/test_browser_youtube_e2e.py
    python server/testing/test_browser_youtube_e2e.py --query "trending music"
    python server/testing/test_browser_youtube_e2e.py --dry-run

Pytest:
    pytest server/testing/test_browser_youtube_e2e.py -v -s
"""
from __future__ import annotations

import argparse
import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from plugins.installed.web.tools.browser_action import BrowserActionTool
from plugins.installed.web.browser.events import (
    BrowserEvent,
    BrowserEventType,
    get_event_bus,
)


CDP_HOST = "127.0.0.1"
CDP_PORT = 9222
CHROME_PROFILE = Path.home() / ".chrome-debug-profile"


# ─── Chrome bring-up ────────────────────────────────────────────────────────

def _cdp_is_up() -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        return sock.connect_ex((CDP_HOST, CDP_PORT)) == 0
    finally:
        sock.close()


def _find_chrome() -> str | None:
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def ensure_chrome_debug(timeout_s: float = 15.0) -> None:
    """Make sure Chrome is listening on CDP_PORT. Start it if not.

    Raises RuntimeError if Chrome can't be reached/launched — the test
    cannot pretend to succeed without a real browser.
    """
    if _cdp_is_up():
        return

    chrome = _find_chrome()
    if not chrome:
        raise RuntimeError(
            f"Chrome not found and no CDP on :{CDP_PORT}. "
            f"Install Chrome or launch manually with "
            f"--remote-debugging-port={CDP_PORT}."
        )

    CHROME_PROFILE.mkdir(exist_ok=True)
    subprocess.Popen(
        [
            chrome,
            f"--remote-debugging-port={CDP_PORT}",
            f"--user-data-dir={CHROME_PROFILE}",
            "--no-first-run",
            "--no-default-browser-check",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _cdp_is_up():
            time.sleep(0.5)  # give Chrome a beat to be ready for connect_over_cdp
            return
        time.sleep(0.3)

    raise RuntimeError(
        f"Chrome did not open CDP on :{CDP_PORT} within {timeout_s}s"
    )


# ─── Event capture ──────────────────────────────────────────────────────────

class EventRecorder:
    """Subscribe to every event type and store everything for assertions."""

    def __init__(self):
        self.events: list[BrowserEvent] = []
        bus = get_event_bus()
        for et in BrowserEventType:
            bus.subscribe(et, self._on)

    def _on(self, event: BrowserEvent) -> None:
        self.events.append(event)

    def types(self) -> list[str]:
        return [e.type.value for e in self.events]

    def has(self, event_type: BrowserEventType) -> bool:
        return any(e.type == event_type for e in self.events)

    def count(self, event_type: BrowserEventType) -> int:
        return sum(1 for e in self.events if e.type == event_type)


# ─── DOM probe ──────────────────────────────────────────────────────────────

async def _probe_youtube_page() -> dict[str, Any]:
    """After the tool returns, open a fresh CDP connection and inspect
    whatever tab is currently on /watch. We can't reuse the runtime
    inside the tool — it's been disconnected by the time _execute returns.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(f"http://{CDP_HOST}:{CDP_PORT}")
        try:
            # Pick the tab whose URL is most YouTube-like.
            best_page = None
            best_score = -1
            for ctx in browser.contexts:
                for page in ctx.pages:
                    url = (page.url or "").lower()
                    score = 0
                    if "youtube.com" in url:
                        score += 1
                    if "/watch" in url:
                        score += 2
                    if "/results" in url:
                        score += 1
                    if score > best_score:
                        best_score = score
                        best_page = page

            if best_page is None:
                return {"found": False, "reason": "no pages in browser"}

            url = best_page.url
            has_video = await best_page.evaluate(
                "() => !!document.querySelector('video')"
            )
            video_state = await best_page.evaluate(
                """
                () => {
                    const v = document.querySelector('video');
                    if (!v) return null;
                    return {
                        paused: v.paused,
                        ended: v.ended,
                        currentTime: v.currentTime,
                        readyState: v.readyState,
                    };
                }
                """
            )
            title = await best_page.title()
            return {
                "found": True,
                "url": url,
                "title": title,
                "has_video": bool(has_video),
                "video_state": video_state,
            }
        finally:
            # IMPORTANT: do NOT call browser.close() here. For a CDP-attached
            # browser, close() can terminate the Chrome process on Windows,
            # which then breaks every subsequent test run (port 9222 gone).
            # Exiting the `async with async_playwright()` block disconnects
            # the websocket cleanly without touching Chrome itself.
            pass


# ─── The test ───────────────────────────────────────────────────────────────

async def play_youtube_via_tool(query: str, dry_run: bool) -> dict[str, Any]:
    """Run one end-to-end flow and return a fact dict for assertions."""
    ensure_chrome_debug()

    recorder = EventRecorder()

    # Dry-run path: BrowserActionTool.play_media hardcodes dry_run=False
    # when delegating, so we call BrowserAgentTool directly to actually
    # exercise the dry-run code in the runtime.
    if dry_run:
        from plugins.installed.web.browser.tool import BrowserAgentTool
        agent_result = await BrowserAgentTool()._execute(
            {"intent": "youtube_play", "query": query, "dry_run": True}
        )
        return {
            "tool_result": None,
            "agent_result": agent_result,
            "events": recorder.events,
            "recorder": recorder,
            "page": None,
        }

    # Real path: go through the public BrowserActionTool surface so we
    # also cover browser_action.py → BrowserAgentTool wiring.
    tool = BrowserActionTool()
    tool_result = await tool._execute(
        {"action": "play_media", "title": query}
    )

    # Give the page a moment to actually start the video — verify_goal_completed
    # checks `!v.paused`, but YouTube autoplay can race the read.
    await asyncio.sleep(2.0)
    page_facts = await _probe_youtube_page()

    return {
        "tool_result": tool_result,
        "agent_result": None,
        "events": recorder.events,
        "recorder": recorder,
        "page": page_facts,
    }


# ─── Assertions ─────────────────────────────────────────────────────────────

def assert_real_run(facts: dict[str, Any]) -> None:
    tool_result = facts["tool_result"]
    recorder: EventRecorder = facts["recorder"]
    page = facts["page"]

    # 1. The tool succeeded
    assert tool_result.success, (
        f"BrowserActionTool failed: error={tool_result.error!r} "
        f"data={tool_result.data!r}"
    )

    # 2. play_media delegated to BrowserAgentTool (not the URL-open fallback)
    assert tool_result.data.get("automated") is True, (
        "play_media should have delegated to BrowserAgentTool, but ran "
        f"the fallback. data={tool_result.data!r}"
    )

    # 3. Lifecycle events fired
    assert recorder.has(BrowserEventType.FLOW_STARTED), (
        f"expected FLOW_STARTED, got: {recorder.types()}"
    )
    assert recorder.has(BrowserEventType.FLOW_COMPLETED), (
        f"expected FLOW_COMPLETED, got: {recorder.types()}"
    )
    assert recorder.count(BrowserEventType.ACTION_FINISHED) >= 3, (
        f"expected at least 3 ACTION_FINISHED (home, search, click) — "
        f"got {recorder.count(BrowserEventType.ACTION_FINISHED)}: "
        f"{recorder.types()}"
    )

    # 4. Safety: play_media MUST NOT hit a payment page
    assert not recorder.has(BrowserEventType.PAYMENT_PAGE_REACHED), (
        "play_media triggered PAYMENT_PAGE_REACHED — that's a serious "
        "regression. Payment intent must never originate from a video flow."
    )
    assert not recorder.has(BrowserEventType.FLOW_ABORTED), (
        f"flow aborted: {[e.data for e in recorder.events if e.type == BrowserEventType.FLOW_ABORTED]}"
    )

    # 5. The browser actually landed on a video page
    assert page and page.get("found"), f"no YouTube page found in browser: {page!r}"
    url = page["url"]
    assert "youtube.com" in url.lower(), f"final URL not on youtube: {url}"
    assert "/watch" in url.lower(), (
        f"final URL is not a video page — adapter did not click into a result. "
        f"url={url}"
    )
    assert page["has_video"], "no <video> element on the page"
    state = page.get("video_state") or {}
    assert state.get("readyState", 0) >= 2, (
        f"video never loaded enough to play: readyState={state.get('readyState')}"
    )


def assert_dry_run(facts: dict[str, Any]) -> None:
    agent_result = facts["agent_result"]
    assert agent_result is not None
    assert agent_result.success, (
        f"dry-run failed: error={agent_result.error!r} data={agent_result.data!r}"
    )
    assert agent_result.data.get("dry_run") is True
    # No /watch navigation should have happened — but we don't probe the page
    # for dry-run because the runtime never clicked anything real.


# ─── Pytest entry points ────────────────────────────────────────────────────

def test_youtube_play_real():
    """pytest entry: real browser, real YouTube, hard assertions."""
    facts = asyncio.run(play_youtube_via_tool("lofi beats", dry_run=False))
    assert_real_run(facts)


def test_youtube_play_dry_run():
    """pytest entry: dry-run path should succeed without clicking."""
    facts = asyncio.run(play_youtube_via_tool("lofi beats", dry_run=True))
    assert_dry_run(facts)


# ─── Standalone runner ──────────────────────────────────────────────────────

def _ascii(s: Any) -> str:
    """Coerce to a string the Windows cp1252 console can definitely print."""
    return str(s).encode("ascii", "replace").decode("ascii")


def _print_facts(facts: dict[str, Any]) -> None:
    tr = facts["tool_result"]
    if tr is not None:
        print(f"\ntool.success = {tr.success}")
        print(f"tool.data    = {_ascii(tr.data)}")
        if tr.error:
            print(f"tool.error   = {_ascii(tr.error)}")
    if facts.get("recorder"):
        events = facts["recorder"].events
        print(f"\nevents ({len(events)}):")
        for e in events:
            # Always print step/abort detail so failures are debuggable.
            relevant = {
                BrowserEventType.FLOW_STARTED:          ("run_id", "intent"),
                BrowserEventType.FLOW_ABORTED:          ("error_type", "detail"),
                BrowserEventType.FLOW_COMPLETED:        ("state",),
                BrowserEventType.ACTION_STARTED:        ("step", "goal"),
                BrowserEventType.ACTION_FINISHED:       ("step", "ok", "confidence", "error_type", "error_detail", "target"),
                BrowserEventType.AWAITING_USER:         ("reason", "url"),
                BrowserEventType.RECOVERY_TRIGGERED:    None,
                BrowserEventType.PAYMENT_PAGE_REACHED:  ("url", "approved"),
                BrowserEventType.BROWSER_DEAD:          None,
                BrowserEventType.TAB_CRASHED:           None,
            }
            keys = relevant.get(e.type)
            if keys is None:
                detail = e.data
            else:
                detail = {k: e.data.get(k) for k in keys if k in e.data}
            print(f"  - {e.type.value:18} {_ascii(detail)}")
    if facts.get("page"):
        print(f"\npage:")
        for k, v in facts["page"].items():
            print(f"  {k:12} = {_ascii(v)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="lofi beats", help="YouTube search query")
    parser.add_argument("--dry-run", action="store_true", help="Dry-run mode")
    args = parser.parse_args()

    print("=" * 60)
    print(f"YouTube e2e — query={args.query!r} dry_run={args.dry_run}")
    print("=" * 60)

    try:
        facts = asyncio.run(play_youtube_via_tool(args.query, dry_run=args.dry_run))
    except RuntimeError as e:
        print(f"\n✗ Setup failed: {e}")
        return 2

    _print_facts(facts)

    try:
        if args.dry_run:
            assert_dry_run(facts)
        else:
            assert_real_run(facts)
    except AssertionError as e:
        print(f"\n[FAIL] ASSERTION FAILED:\n  {e}")
        return 1

    print("\n[PASS]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
