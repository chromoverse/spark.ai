"""Volume, media keys, brightness. Windows first (RULES §1); other platforms say so clearly.
pycaw / screen-brightness-control are optional (`hands` extra): without them, volume falls back to
volume keys and brightness to WMI."""

from __future__ import annotations

import subprocess
import sys
import urllib.parse
import webbrowser
from typing import Any

VK = {
    "volume_mute": 0xAD,
    "volume_down": 0xAE,
    "volume_up": 0xAF,
    "next": 0xB0,
    "previous": 0xB1,
    "play_pause": 0xB3,
}
KEY_STEP = 2  # Windows moves the volume 2% per volume key press


class Unsupported(Exception):
    pass


def _windows() -> None:
    if sys.platform != "win32":
        raise Unsupported("That only works on Windows for now.")


def _press(key: str, times: int = 1) -> None:
    _windows()
    import ctypes

    user32 = ctypes.windll.user32
    for _ in range(times):
        user32.keybd_event(VK[key], 0, 0, 0)
        user32.keybd_event(VK[key], 0, 2, 0)  # KEYEVENTF_KEYUP


def _endpoint() -> Any | None:
    try:
        from pycaw.pycaw import AudioUtilities
    except ImportError:
        return None
    return AudioUtilities.GetSpeakers().EndpointVolume


def volume_set(inp: dict[str, Any]) -> dict[str, Any]:
    _windows()
    level = int(inp["level"])
    ep = _endpoint()
    if ep is not None:
        ep.SetMasterVolumeLevelScalar(level / 100, None)
    else:
        # ponytail: no pycaw → bottom out with volume keys, then step up. Exact to 2%.
        _press("volume_down", 100 // KEY_STEP)
        _press("volume_up", round(level / KEY_STEP))
    return {"level": level}


def volume_change(inp: dict[str, Any]) -> dict[str, Any]:
    _windows()
    step = int(inp.get("step", 10))
    up = inp["direction"] == "up"
    ep = _endpoint()
    if ep is not None:
        now = round(ep.GetMasterVolumeLevelScalar() * 100)
        level = max(0, min(100, now + (step if up else -step)))
        ep.SetMasterVolumeLevelScalar(level / 100, None)
        return {"level": level}
    _press("volume_up" if up else "volume_down", max(1, round(step / KEY_STEP)))
    return {"direction": inp["direction"], "step": step}


def volume_mute(inp: dict[str, Any]) -> dict[str, Any]:
    _windows()
    ep = _endpoint()
    if ep is None:
        _press("volume_mute")  # a toggle: without pycaw the current state is unknown
        return {"toggled": True}
    ep.SetMute(1 if inp["mute"] else 0, None)
    return {"muted": bool(inp["mute"])}


def media_control(inp: dict[str, Any]) -> dict[str, Any]:
    action = inp["action"]
    # ponytail: play/pause/toggle share the one play-pause key; the OS doesn't say which state
    # it's in. Per-app control (SMTC) can replace this if "pause" ever resumes something.
    _press({"next": "next", "previous": "previous"}.get(action, "play_pause"))
    return {"action": action}


def media_play(inp: dict[str, Any]) -> dict[str, Any]:
    query = str(inp["query"])
    app = (inp.get("app") or "").lower()
    if "spotify" in app:
        url = "spotify:search:" + urllib.parse.quote(query)
        where = "Spotify"
    else:
        url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query)
        where = "YouTube"
    if not webbrowser.open(url):
        raise Unsupported(f"Couldn't open {where} on this device.")
    return {"searching": query, "in": where}


def brightness_set(inp: dict[str, Any]) -> dict[str, Any]:
    level = int(inp["level"])
    try:
        import screen_brightness_control as sbc

        sbc.set_brightness(level)
        return {"level": level}
    except ImportError:
        pass
    _windows()
    script = (
        "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods)"
        f".WmiSetBrightness(1,{level})"
    )
    done = subprocess.run(  # noqa: S603 (fixed command, integer argument)
        ["powershell", "-NoProfile", "-Command", script],  # noqa: S607
        capture_output=True,
        timeout=8,
        check=False,
    )
    if done.returncode != 0:
        raise Unsupported("This screen doesn't let me change its brightness.")
    return {"level": level}


def battery_status(inp: dict[str, Any]) -> dict[str, Any]:
    """Read-only: battery percent and whether it's charging (tier 0 answers it out loud)."""
    from spark_body.fitness.hardware import power

    p = power()
    if p["battery_pct"] is None:
        raise Unsupported("This PC doesn't report a battery.")
    return {"battery_pct": p["battery_pct"], "plugged": p["plugged"]}
