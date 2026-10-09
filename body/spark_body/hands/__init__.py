"""Device tools (REDESIGN §7.3). Each takes the brain-validated input dict and returns an output
dict, or raises ToolFailure with a message the model can act on (API.md §3.3)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from spark_body.hands import apps, system


class ToolFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


Hand = Callable[[dict[str, Any]], dict[str, Any]]

# Blocking OS calls; run() moves them off the event loop.
HANDS: dict[str, Hand] = {
    "volume_set": system.volume_set,
    "volume_change": system.volume_change,
    "volume_mute": system.volume_mute,
    "media_control": system.media_control,
    "media_play": system.media_play,
    "brightness_set": system.brightness_set,
    "app_open": apps.app_open,
}


async def run(tool: str, inp: dict[str, Any]) -> dict[str, Any]:
    hand = HANDS.get(tool)
    if hand is None:
        raise ToolFailure("unknown_tool", f"This device doesn't have a {tool} tool.")
    try:
        return await asyncio.to_thread(hand, inp)
    except system.Unsupported as exc:
        raise ToolFailure("unsupported", str(exc)) from None
    except apps.NotInstalled as exc:
        raise ToolFailure("not_installed", str(exc)) from None
