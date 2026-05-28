"""Smoke test for the media_control tool.

Sequence:
  1. Start a YouTube video via the existing browser_action play_media path.
  2. Run a battery of media_control commands against the live tab and
     verify each one actually changed the player state.
  3. Each assertion reads the page back, so we never trust the JS return
     value alone — the browser is the source of truth.

Usage:
    python server/testing/test_media_control.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from plugins.installed.web.tools.browser_action import BrowserActionTool
from plugins.installed.web.tools.media_control import MediaControlTool
from plugins.installed.web.browser.session import (
    get_browser_session,
    shutdown_browser_session,
)
from testing.test_browser_youtube_e2e import ensure_chrome_debug


async def _read_state() -> dict:
    """Inspect the live YouTube tab via the session — fresh read every time."""
    page = await get_browser_session().get_page("youtube.com", focus=False)
    return await page.evaluate("""
        () => {
            const v = document.querySelector('video');
            if (!v) return null;
            return {
                paused: v.paused,
                muted: v.muted,
                volume: v.volume,
                currentTime: v.currentTime,
                url: location.href,
            };
        }
    """)


async def main() -> int:
    ensure_chrome_debug()

    # 1. Make sure something is playing.
    print("-> Priming: play 'lofi beats'")
    play = await BrowserActionTool()._execute(
        {"action": "play_media", "title": "lofi beats"}
    )
    assert play.success and play.data.get("automated"), play.data
    await asyncio.sleep(2.0)  # let autoplay start

    tool = MediaControlTool()

    async def call(control: str, **extra):
        return await tool._execute({"control": control, **extra})

    # 2. status — sanity check
    print("-> status")
    r = await call("status")
    assert r.success, r.error
    assert "paused" in r.data, r.data
    print(f"   paused={r.data['paused']} volume={r.data['volume']:.2f}")

    # 3. pause
    print("-> pause")
    r = await call("pause")
    assert r.success, r.error
    await asyncio.sleep(0.3)
    s = await _read_state()
    assert s and s["paused"] is True, f"expected paused, got {s}"

    # 4. play
    print("-> play")
    r = await call("play")
    assert r.success, r.error
    await asyncio.sleep(0.3)
    s = await _read_state()
    assert s and s["paused"] is False, f"expected playing, got {s}"

    # 5. toggle -> should pause again
    print("-> toggle")
    r = await call("toggle")
    assert r.success, r.error
    await asyncio.sleep(0.3)
    s = await _read_state()
    assert s and s["paused"] is True, f"expected paused after toggle, got {s}"

    # 6. mute
    print("-> mute")
    r = await call("mute")
    assert r.success, r.error
    s = await _read_state()
    assert s and s["muted"] is True

    # 7. unmute
    print("-> unmute")
    r = await call("unmute")
    assert r.success, r.error
    s = await _read_state()
    assert s and s["muted"] is False

    # 8. volume to 0.3
    print("-> volume = 0.3")
    r = await call("volume", level=0.3)
    assert r.success, r.error
    s = await _read_state()
    assert s and abs(s["volume"] - 0.3) < 0.01, f"expected ~0.3, got {s['volume']}"

    # 9. volume_up — should rise by ~0.1
    print("-> volume_up")
    before = s["volume"]
    r = await call("volume_up")
    assert r.success, r.error
    s = await _read_state()
    assert s["volume"] > before, f"expected volume to rise, before={before} after={s['volume']}"

    # 10. volume_down — should fall
    print("-> volume_down")
    before = s["volume"]
    r = await call("volume_down")
    assert r.success, r.error
    s = await _read_state()
    assert s["volume"] < before, f"expected volume to drop, before={before} after={s['volume']}"

    # 11. seek_forward 5s
    print("-> seek_forward 5s")
    # Resume playback first so currentTime can advance / be observed cleanly
    await call("play")
    await asyncio.sleep(0.3)
    s_before = await _read_state()
    r = await call("seek_forward", seconds=5)
    assert r.success, r.error
    s_after = await _read_state()
    # Allow a small fudge for playback drift during the call (~0.5s).
    assert s_after["currentTime"] >= s_before["currentTime"] + 4.0, (
        f"seek_forward didn't move enough: {s_before['currentTime']} -> {s_after['currentTime']}"
    )

    # 12. seek_back 3s
    print("-> seek_back 3s")
    s_before = await _read_state()
    r = await call("seek_back", seconds=3)
    assert r.success, r.error
    s_after = await _read_state()
    assert s_after["currentTime"] <= s_before["currentTime"] - 2.0, (
        f"seek_back didn't move enough: {s_before['currentTime']} -> {s_after['currentTime']}"
    )

    # 13. skip_ad — almost certainly no ad, should return ok=False with reason
    print("-> skip_ad (no ad expected)")
    r = await call("skip_ad")
    assert not r.success  # No ad → not a real success, but not a crash either.
    assert r.error and "skip button" in r.error.lower(), r.error

    # 14. Invalid control rejected
    print("-> invalid control rejected")
    r = await call("explode")
    assert not r.success
    assert "Unknown control" in (r.error or "")

    print("\n[PASS] media_control commands all behaved as expected.")
    await shutdown_browser_session()
    return 0


if __name__ == "__main__":
    try:
        rc = asyncio.run(main())
    except AssertionError as e:
        print(f"\n[FAIL] {e}")
        rc = 1
    sys.exit(rc)
