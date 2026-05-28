"""Verify the persistent BrowserSession survives across calls.

What this proves
────────────────
1. Two back-to-back play_media calls in the same Python process use the
   *same* runtime instance (no per-call reconnect).
2. The second call updates the existing YouTube tab — no duplicate tabs
   pile up. (Same tab handle, URL changes, page count unchanged.)
3. The shared session keeps the runtime alive between calls; the tool
   never disconnects it.

This is the test the one-shot e2e can't cover because each script
invocation is its own process and creates its own session.

Usage:
    python server/testing/test_browser_session_reuse.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from plugins.installed.web.tools.browser_action import BrowserActionTool
from plugins.installed.web.browser.session import (
    get_browser_session,
    shutdown_browser_session,
)

# Reuse the Chrome bring-up + DOM probe helpers from the e2e module.
from testing.test_browser_youtube_e2e import ensure_chrome_debug, _probe_youtube_page


async def _youtube_tab_count() -> int:
    """How many YouTube tabs does the live session see right now?"""
    runtime = await get_browser_session().runtime()
    pages = await runtime.pages()
    return sum(1 for p in pages if "youtube.com" in (p.url or "").lower())


async def main() -> int:
    ensure_chrome_debug()

    tool = BrowserActionTool()

    # First play.
    print("-> Play #1: 'lofi beats'")
    r1 = await tool._execute({"action": "play_media", "title": "lofi beats"})
    assert r1.success, f"first play failed: {r1.error}"
    assert r1.data.get("automated") is True, f"first play not automated: {r1.data}"

    runtime_after_1 = await get_browser_session().runtime()
    tabs_after_1 = await _youtube_tab_count()
    await asyncio.sleep(2.0)
    page1 = await _probe_youtube_page()
    assert page1.get("found") and "/watch" in page1["url"], page1
    url_1 = page1["url"]
    print(f"  tab count={tabs_after_1}  url={url_1[:60]}...")

    # Second play — should hit the SAME tab (no new YouTube tab spawned)
    # and the SAME runtime instance (no reconnect).
    print("-> Play #2: 'morning songs'")
    r2 = await tool._execute({"action": "play_media", "title": "morning songs"})
    assert r2.success, f"second play failed: {r2.error}"

    runtime_after_2 = await get_browser_session().runtime()
    tabs_after_2 = await _youtube_tab_count()
    await asyncio.sleep(2.0)
    page2 = await _probe_youtube_page()
    assert page2.get("found") and "/watch" in page2["url"], page2
    url_2 = page2["url"]
    print(f"  tab count={tabs_after_2}  url={url_2[:60]}...")

    # ── Assertions ──────────────────────────────────────────────────────
    assert runtime_after_1 is runtime_after_2, (
        "BrowserSession returned a different runtime between calls — the "
        "session reconnected instead of reusing the live connection."
    )
    assert tabs_after_1 == tabs_after_2, (
        f"YouTube tab count grew: {tabs_after_1} -> {tabs_after_2}. The "
        "second flow should have reused the existing tab, not spawned a new one."
    )
    assert url_1 != url_2, (
        "Both plays landed on the exact same URL — the second search did "
        "not actually navigate."
    )

    print("\n[PASS] Session reuse verified:")
    print(f"  same runtime instance:  OK")
    print(f"  same YouTube tab count: OK ({tabs_after_2})")
    print(f"  url changed:            OK")

    # Shut down inside the same event loop — playwright's objects are bound
    # to the loop they were created on, so a fresh asyncio.run can't close them.
    await shutdown_browser_session()
    return 0


if __name__ == "__main__":
    try:
        rc = asyncio.run(main())
    except AssertionError as e:
        print(f"\n[FAIL] {e}")
        rc = 1
    sys.exit(rc)
