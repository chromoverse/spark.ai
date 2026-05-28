"""End-to-end test for the Spotify Web adapter.

First-run gotcha
────────────────
Spotify requires sign-in. The auth helper will:
  1. Detect you're not signed in.
  2. Send the live tab to https://accounts.spotify.com/en/login.
  3. Pull Chrome to the foreground.
  4. Block for up to 5 minutes waiting for the signed-in marker
     (the user avatar in the top right) to appear.

So the *first* time you run this, sign in in the Chrome window when it
appears. The persistent profile (~/.chrome-debug-profile) will carry
the session forever after — subsequent runs are fully automated.

Usage:
    python server/testing/test_browser_spotify_e2e.py
    python server/testing/test_browser_spotify_e2e.py --query "arctic monkeys"
    python server/testing/test_browser_spotify_e2e.py --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from plugins.installed.web.tools.browser_action import BrowserActionTool
from plugins.installed.web.browser.events import BrowserEventType
from plugins.installed.web.browser.session import shutdown_browser_session

from testing.test_browser_youtube_e2e import ensure_chrome_debug, EventRecorder


async def _probe_spotify_page() -> dict[str, Any]:
    """Inspect the live Spotify tab to confirm a track is playing."""
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
        best = None
        best_score = -1
        for ctx in browser.contexts:
            for page in ctx.pages:
                url = (page.url or "").lower()
                score = 0
                if "open.spotify.com" in url:
                    score += 2
                if "/search" in url:
                    score += 1
                if score > best_score:
                    best_score = score
                    best = page
        if best is None:
            return {"found": False, "reason": "no Spotify tab"}

        url = best.url
        title = await best.title()
        has_now_playing = await best.evaluate(
            """
            () => {
                const w = document.querySelector('[data-testid="now-playing-widget"]');
                if (!w) return false;
                const link = w.querySelector('[data-testid="context-item-link"]');
                return !!link;
            }
            """
        )
        media_state = await best.evaluate(
            """
            () => {
                const els = [...document.querySelectorAll('audio,video')];
                if (!els.length) return null;
                const e = els.find(x => !x.paused && x.currentTime > 0) || els[0];
                return {paused: e.paused, currentTime: e.currentTime,
                        readyState: e.readyState, tag: e.tagName};
            }
            """
        )
        return {
            "found": True, "url": url, "title": title,
            "has_now_playing": bool(has_now_playing),
            "media_state": media_state,
        }


async def run(query: str, dry_run: bool) -> dict[str, Any]:
    ensure_chrome_debug()
    recorder = EventRecorder()

    if dry_run:
        from plugins.installed.web.browser.tool import BrowserAgentTool
        result = await BrowserAgentTool()._execute(
            {"intent": "spotify_play", "query": query, "dry_run": True}
        )
        return {"tool_result": None, "agent_result": result,
                "recorder": recorder, "page": None}

    tool_result = await BrowserActionTool()._execute(
        {"action": "play_music", "title": query}
    )
    # Give Spotify's audio element a couple of seconds to actually start.
    await asyncio.sleep(3.0)
    page_facts = await _probe_spotify_page()
    return {"tool_result": tool_result, "agent_result": None,
            "recorder": recorder, "page": page_facts}


def assert_real_run(facts: dict[str, Any]) -> None:
    tr = facts["tool_result"]
    rec: EventRecorder = facts["recorder"]
    page = facts["page"]

    assert tr.success, f"tool failed: error={tr.error!r} data={tr.data!r}"
    assert tr.data.get("automated") is True, (
        f"play_music did not run the adapter (fell back to URL open). data={tr.data!r}"
    )
    assert rec.has(BrowserEventType.FLOW_STARTED), rec.types()
    assert rec.has(BrowserEventType.FLOW_COMPLETED), rec.types()

    assert page and page.get("found"), f"no Spotify tab: {page!r}"
    url = page["url"]
    assert "open.spotify.com" in url, f"final URL not Spotify: {url}"

    # Either the now-playing widget OR a non-paused media element is enough.
    media = page.get("media_state") or {}
    media_ok = bool(media) and media.get("paused") is False and media.get("currentTime", 0) > 0
    assert page.get("has_now_playing") or media_ok, (
        f"Spotify did not actually start playing — now_playing={page.get('has_now_playing')} "
        f"media={media}"
    )


def _ascii(s: Any) -> str:
    return str(s).encode("ascii", "replace").decode("ascii")


def _print_facts(f: dict[str, Any]) -> None:
    if f["tool_result"]:
        tr = f["tool_result"]
        print(f"\ntool.success = {tr.success}")
        print(f"tool.data    = {_ascii(tr.data)}")
        if tr.error:
            print(f"tool.error   = {_ascii(tr.error)}")
    if f.get("recorder"):
        events = f["recorder"].events
        print(f"\nevents ({len(events)}):")
        for e in events:
            print(f"  - {e.type.value:20} {_ascii(e.data)}")
    if f.get("page"):
        print(f"\npage:")
        for k, v in f["page"].items():
            print(f"  {k:18} = {_ascii(v)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="lofi hip hop")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("=" * 60)
    print(f"Spotify e2e -- query={args.query!r} dry_run={args.dry_run}")
    print("=" * 60)
    print("First run? Sign in to Spotify when Chrome opens; subsequent runs are automatic.")
    print()

    try:
        facts = asyncio.run(run(args.query, args.dry_run))
    except RuntimeError as e:
        print(f"\n[FAIL] setup: {e}")
        return 2

    _print_facts(facts)

    try:
        if args.dry_run:
            ar = facts["agent_result"]
            assert ar and ar.success, ar
            assert ar.data.get("dry_run") is True
        else:
            assert_real_run(facts)
    except AssertionError as e:
        print(f"\n[FAIL] {e}")
        try:
            asyncio.run(shutdown_browser_session())
        except Exception:
            pass
        return 1

    print("\n[PASS]")
    try:
        asyncio.run(shutdown_browser_session())
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
