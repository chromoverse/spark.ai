"""Interactive REPL for media_control — type commands, watch Chrome react.

What it does
────────────
1. Makes sure Chrome is running on the CDP port (starts it if not).
2. Optionally primes playback with a query (default 'lofi beats') or
   skips priming if you already have a YouTube tab open.
3. Drops you into a prompt where you can type natural shorthand:

       pause
       play / resume
       toggle
       next / prev
       mute / unmute
       vol up / vol down
       vol 0.5                   (exact level)
       skip 30                   (forward 30s)
       back 10                   (rewind 10s)
       skip ad
       fullscreen
       status
       q / quit                  (exit)

Usage:
    python server/testing/repl_media_control.py
    python server/testing/repl_media_control.py --query "morning songs"
    python server/testing/repl_media_control.py --no-prime
"""
from __future__ import annotations

import argparse
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


# ── Command parsing ────────────────────────────────────────────────────────
# Maps the loose REPL syntax to (control, params) tuples. Keep this list
# short and friendly — power users can extend it; the underlying tool
# already accepts every valid control name directly too.

def parse(line: str) -> tuple[str, dict] | None:
    """Translate a free-form line into (control, params). None means 'unknown'."""
    parts = line.strip().lower().split()
    if not parts:
        return None
    head, rest = parts[0], parts[1:]

    # Single-word aliases
    aliases = {
        "pause":      ("pause", {}),
        "play":       ("play", {}),
        "resume":     ("play", {}),
        "toggle":     ("toggle", {}),
        "p":          ("toggle", {}),     # quick toggle
        "next":       ("next", {}),
        "n":          ("next", {}),
        "prev":       ("previous", {}),
        "previous":   ("previous", {}),
        "mute":       ("mute", {}),
        "m":          ("mute", {}),
        "unmute":     ("unmute", {}),
        "fullscreen": ("fullscreen", {}),
        "fs":         ("fullscreen", {}),
        "status":     ("status", {}),
        "s":          ("status", {}),
    }
    if head in aliases and not rest:
        return aliases[head]

    # vol up | vol down | vol 0.4
    if head in ("vol", "volume") and rest:
        sub = rest[0]
        if sub in ("up", "+"):
            return ("volume_up", {})
        if sub in ("down", "-"):
            return ("volume_down", {})
        try:
            level = float(sub)
        except ValueError:
            return None
        return ("volume", {"level": level})

    # skip 30 = forward 30s; skip ad
    if head == "skip":
        if rest and rest[0] == "ad":
            return ("skip_ad", {})
        if rest:
            try:
                return ("seek_forward", {"seconds": float(rest[0])})
            except ValueError:
                return None
        return ("seek_forward", {})

    # forward / back N
    if head in ("forward", "fwd", "f") and rest:
        try:
            return ("seek_forward", {"seconds": float(rest[0])})
        except ValueError:
            return None
    if head in ("back", "rewind", "b") and rest:
        try:
            return ("seek_back", {"seconds": float(rest[0])})
        except ValueError:
            return None

    # Fall-through: maybe they typed the raw control name (e.g. "volume_up")
    return (head, {})


def _fmt_state(d: dict) -> str:
    if not d or not isinstance(d, dict):
        return ""
    bits = []
    if "paused" in d:
        bits.append("PAUSED" if d["paused"] else "PLAYING")
    if "volume" in d:
        bits.append(f"vol={d['volume']:.2f}")
    if "muted" in d and d["muted"]:
        bits.append("MUTED")
    if "currentTime" in d:
        bits.append(f"t={d['currentTime']:.1f}s")
    return "  ".join(bits)


# ── Main loop ──────────────────────────────────────────────────────────────

HELP = """
Commands:
  pause                       play / resume / toggle (p)
  next (n) / prev             skip to next / previous in autoplay queue
  mute (m) / unmute
  vol up / vol down           +/- 10%
  vol 0.5                     exact level
  skip 30                     forward 30 seconds
  back 10                     rewind 10 seconds
  skip ad
  fullscreen (fs)
  status (s)
  help (?) / quit (q)
"""


async def run(prime_query: str | None) -> int:
    ensure_chrome_debug()
    tool = MediaControlTool()

    if prime_query:
        print(f"[priming] play_media: {prime_query!r}")
        r = await BrowserActionTool()._execute(
            {"action": "play_media", "title": prime_query}
        )
        if not r.success or not r.data.get("automated"):
            print(f"[warn] priming did not run the automated flow: {r.data}")
        await asyncio.sleep(1.5)

    print(HELP)
    print("Type a command. Empty line repeats `status`. q to quit.\n")

    last_cmd: tuple[str, dict] | None = ("status", {})

    while True:
        try:
            line = await asyncio.to_thread(input, "media> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        s = line.strip().lower()
        if s in ("q", "quit", "exit"):
            break
        if s in ("?", "help"):
            print(HELP)
            continue

        if not s:
            parsed = last_cmd
        else:
            parsed = parse(s)
            if parsed is None:
                print(f"  ? don't know how to run {line!r}. Type 'help'.")
                continue
            last_cmd = parsed

        control, params = parsed
        result = await tool._execute({"control": control, **params})
        tag = "ok " if result.success else "err"
        state = _fmt_state(result.data)
        line_out = f"  [{tag}] {control}"
        if params:
            line_out += f" {params}"
        if state:
            line_out += f"   {state}"
        if not result.success and result.error:
            line_out += f"   <{result.error}>"
        print(line_out)

    await shutdown_browser_session()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="lofi beats",
                        help="Initial play_media query (default: 'lofi beats')")
    parser.add_argument("--no-prime", action="store_true",
                        help="Skip priming — assume a YouTube tab is already open")
    args = parser.parse_args()

    prime = None if args.no_prime else args.query
    try:
        return asyncio.run(run(prime))
    except RuntimeError as e:
        print(f"[setup error] {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
