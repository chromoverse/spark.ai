"""Device tools (REDESIGN §7.3). Each takes the brain-validated input dict and returns an output
dict, or raises ToolFailure with a message the model can act on (API.md §3.3)."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from collections.abc import Callable
from typing import Any

from spark_body.hands import apps, desktop, files, shell, system
from spark_body.hands.errors import ToolFailure, Unsupported

__all__ = ["CAPABILITIES", "HANDS", "ToolFailure", "run"]

logger = logging.getLogger(__name__)

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
    "app_list": apps.app_list,
    "app_close": desktop.app_close,
    "battery_status": system.battery_status,
    "file_read": files.file_read,
    "file_list": files.file_list,
    "file_search": files.file_search,
    "file_write": files.file_write,
    "file_edit": files.file_edit,
    "file_move": files.file_move,
    "file_delete": files.file_delete,
    "file_open": files.file_open,
    "folder_organize": files.folder_organize,
    "folder_organize_restore": files.folder_organize_restore,
    "shell_run": shell.shell_run,
    "clipboard_read": desktop.clipboard_read,
    "clipboard_write": desktop.clipboard_write,
    "screenshot_take": desktop.screenshot_take,
    "keyboard_type": desktop.keyboard_type,
    "keyboard_hotkey": desktop.keyboard_hotkey,
    "mouse_click": desktop.mouse_click,
    "process_list": desktop.process_list,
    "process_kill": desktop.process_kill,
    "system_info": desktop.system_info,
    "system_lock": desktop.system_lock,
    "system_sleep": desktop.system_sleep,
}

# What device.hello reports; the brain only offers tools whose `requires` this covers.
_EVERYWHERE = {"files", "shell", "system", "tts"}
_WINDOWS = {
    "apps",
    "media",
    "volume",
    "brightness",
    "clipboard",
    "screen",
    "input",
    "processes",
    "power",
}
CAPABILITIES = sorted(_EVERYWHERE | (_WINDOWS if sys.platform == "win32" else set()))


async def run(tool: str, inp: dict[str, Any]) -> dict[str, Any]:
    hand = HANDS.get(tool)
    if hand is None:
        raise ToolFailure("unknown_tool", f"This device doesn't have a {tool} tool.")
    try:
        return await asyncio.to_thread(hand, inp)
    except ToolFailure:
        raise
    except Unsupported as exc:
        raise ToolFailure("unsupported", str(exc)) from None
    except apps.NotInstalled as exc:
        raise ToolFailure("not_installed", str(exc)) from None
    except PermissionError as exc:
        where = f" {exc.filename}" if exc.filename else ""
        raise ToolFailure(
            "denied", f"Windows won't let me touch{where} (permission denied)."
        ) from None
    except FileNotFoundError as exc:
        where = f" {exc.filename}" if exc.filename else " that"
        raise ToolFailure("not_found", f"I couldn't find{where}.") from None
    except OSError as exc:
        raise ToolFailure(
            "failed", f"{tool} failed: {exc.strerror or type(exc).__name__}."
        ) from None
    except subprocess.TimeoutExpired:
        raise ToolFailure("timeout", f"{tool} took too long, so I stopped it.") from None
    except Exception as exc:
        logger.exception("hand %s crashed", tool)
        raise ToolFailure(
            "failed", f"{tool} broke on this device ({type(exc).__name__})."
        ) from None
