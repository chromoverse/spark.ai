"""Clipboard, screenshot, keyboard, mouse, processes, and power (REDESIGN §7.3). Windows first:
input goes through SendInput, clipboard and screenshots through PowerShell (both ship with
Windows, nothing to install)."""

from __future__ import annotations

import csv
import io
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime
from typing import Any

from spark_body.hands.errors import ToolFailure, Unsupported
from spark_body.hands.files import known_folder


def _windows() -> None:
    if sys.platform != "win32":
        raise Unsupported("That only works on Windows for now.")


def _ps(script: str, stdin: str | None = None, timeout: float = 15) -> str:
    _windows()
    done = subprocess.run(  # noqa: S603 (fixed scripts; user text goes through stdin)
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],  # noqa: S607
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if done.returncode != 0:
        raise ToolFailure("failed", done.stderr.strip()[:300] or "PowerShell said no.")
    return done.stdout


# ── clipboard ─────────────────────────────────────────────────────────────────────────────


def clipboard_read(inp: dict[str, Any]) -> dict[str, Any]:
    text = _ps("[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw")
    return {"text": text.rstrip("\r\n")[:20000]}


def clipboard_write(inp: dict[str, Any]) -> dict[str, Any]:
    text = str(inp["text"])
    _ps(
        "[Console]::InputEncoding=[Text.Encoding]::UTF8;"
        "Set-Clipboard -Value ([Console]::In.ReadToEnd())",
        stdin=text,
    )
    return {"copied": len(text)}


# ── screen ────────────────────────────────────────────────────────────────────────────────


def screenshot_take(inp: dict[str, Any]) -> dict[str, Any]:
    pictures = known_folder("pictures")
    assert pictures is not None  # known names always resolve
    folder = pictures / "Screenshots"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"Spark {datetime.now():%Y-%m-%d %H%M%S}.png"
    script = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
        "$b=[Windows.Forms.SystemInformation]::VirtualScreen;"
        "$i=New-Object Drawing.Bitmap $b.Width,$b.Height;"
        "$g=[Drawing.Graphics]::FromImage($i);"
        "$g.CopyFromScreen($b.Left,$b.Top,0,0,$i.Size);"
        "$i.Save([Console]::In.ReadToEnd(),[Drawing.Imaging.ImageFormat]::Png);"
        'Write-Output "$($b.Width)x$($b.Height)"'
    )
    size = _ps(script, stdin=str(path)).strip()
    return {"path": str(path).replace("\\", "/"), "size": size}


# ── keyboard + mouse (SendInput) ──────────────────────────────────────────────────────────

VK = {
    "ctrl": 0x11,
    "control": 0x11,
    "alt": 0x12,
    "shift": 0x10,
    "win": 0x5B,
    "windows": 0x5B,
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "esc": 0x1B,
    "escape": 0x1B,
    "space": 0x20,
    "backspace": 0x08,
    "delete": 0x2E,
    "del": 0x2E,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "insert": 0x2D,
    "printscreen": 0x2C,
}
VK |= {f"f{n}": 0x6F + n for n in range(1, 13)}
_KEYUP, _UNICODE = 0x0002, 0x0004


def _vk(key: str) -> int:
    k = key.lower().strip()
    if k in VK:
        return VK[k]
    if len(k) == 1 and (k.isalnum()):
        return ord(k.upper())
    raise ToolFailure(
        "invalid_key",
        f"I don't know the key {key!r}. Try ctrl, alt, shift, win, enter, a-z, 0-9, f1-f12.",
    )


def _send(events: list[tuple[int, int, int]]) -> None:
    """(vk, scan, flags) keyboard events through SendInput."""
    _windows()
    import ctypes
    from ctypes import wintypes

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]

        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    arr = (INPUT * len(events))()
    for i, (vk, scan, flags) in enumerate(events):
        arr[i].type = 1  # INPUT_KEYBOARD
        arr[i].ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    if ctypes.windll.user32.SendInput(len(events), arr, ctypes.sizeof(INPUT)) != len(events):
        raise ToolFailure(
            "blocked", "Windows blocked the keystrokes (an admin window may have focus)."
        )


def keyboard_type(inp: dict[str, Any]) -> dict[str, Any]:
    text = str(inp["text"])
    events: list[tuple[int, int, int]] = []
    for ch in text.replace("\r\n", "\n"):
        if ch == "\n":
            events += [(VK["enter"], 0, 0), (VK["enter"], 0, _KEYUP)]
            continue
        data = ch.encode("utf-16-le")  # emoji become two units (a surrogate pair)
        for i in range(0, len(data), 2):
            code = int.from_bytes(data[i : i + 2], "little")
            events += [(0, code, _UNICODE), (0, code, _UNICODE | _KEYUP)]
    for start in range(0, len(events), 200):  # chunks keep each SendInput call short
        _send(events[start : start + 200])
    return {"typed": len(text)}


def keyboard_hotkey(inp: dict[str, Any]) -> dict[str, Any]:
    keys = [str(k) for k in inp["keys"]]
    codes = [_vk(k) for k in keys]
    _send([(c, 0, 0) for c in codes] + [(c, 0, _KEYUP) for c in reversed(codes)])
    return {"pressed": "+".join(k.lower() for k in keys)}


def mouse_click(inp: dict[str, Any]) -> dict[str, Any]:
    _windows()
    import ctypes

    user32 = ctypes.windll.user32
    x, y = int(inp["x"]), int(inp["y"])
    if not user32.SetCursorPos(x, y):
        raise ToolFailure("failed", "Couldn't move the mouse there.")
    down, up = (0x0008, 0x0010) if inp.get("button") == "right" else (0x0002, 0x0004)
    for _ in range(2 if inp.get("double") else 1):
        user32.mouse_event(down, 0, 0, 0, 0)
        user32.mouse_event(up, 0, 0, 0, 0)
    return {"clicked": [x, y], "button": inp.get("button", "left")}


# ── processes ─────────────────────────────────────────────────────────────────────────────


def _tasks() -> list[dict[str, Any]]:
    _windows()
    out = subprocess.run(
        ["tasklist", "/FO", "CSV", "/NH"],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    ).stdout
    rows = []
    for row in csv.reader(io.StringIO(out)):
        if len(row) >= 5:
            mem = int("".join(c for c in row[4] if c.isdigit()) or 0)
            rows.append({"name": row[0], "pid": int(row[1]), "memory_mb": round(mem / 1024)})
    return rows


def process_list(inp: dict[str, Any]) -> dict[str, Any]:
    want = (inp.get("name") or "").lower()
    rows = [r for r in _tasks() if want in r["name"].lower()]
    merged: dict[str, dict[str, Any]] = {}
    for r in rows:  # 30 chrome.exe rows → one line
        m = merged.setdefault(r["name"], {"name": r["name"], "count": 0, "memory_mb": 0})
        m["count"] += 1
        m["memory_mb"] += r["memory_mb"]
    top = sorted(merged.values(), key=lambda m: -m["memory_mb"])
    return {"processes": top[:40], "total": len(top)}


def _image(name: str) -> str:
    """'chrome' / 'Chrome.exe' → the running image name, matched case-insensitively."""
    want = name.lower().removesuffix(".exe")
    running: dict[str, str] = {
        str(r["name"]).lower().removesuffix(".exe"): str(r["name"]) for r in _tasks()
    }
    if want in running:
        return running[want]
    close = [img for key, img in running.items() if want.replace(" ", "") in key]
    if len(close) == 1:
        return close[0]
    hint = f" Did you mean {', '.join(close[:3])}?" if close else ""
    raise ToolFailure("not_running", f"Nothing called {name} is running.{hint}")


def process_kill(inp: dict[str, Any]) -> dict[str, Any]:
    image = _image(str(inp["name"]))
    done = subprocess.run(  # noqa: S603
        ["taskkill", "/F", "/IM", image],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if done.returncode != 0:
        raise ToolFailure("failed", f"Windows wouldn't close {image}. It may need admin rights.")
    return {"closed": image}


def app_close(inp: dict[str, Any]) -> dict[str, Any]:
    """Asks the app to quit (like clicking X): taskkill without /F sends WM_CLOSE."""
    image = _image(str(inp["app"]))
    subprocess.run(  # noqa: S603
        ["taskkill", "/IM", image],  # noqa: S607
        capture_output=True,
        timeout=10,
        check=False,
    )
    time.sleep(1.5)
    still = any(r["name"].lower() == image.lower() for r in _tasks())
    return {"closed": image, "still_running": still}


# ── system + power ────────────────────────────────────────────────────────────────────────


def _os_name() -> str:
    release = platform.release()
    if sys.platform == "win32" and int(platform.version().split(".")[-1] or 0) >= 22000:
        release = "11"  # Python reports Windows 11 as release "10"; build 22000+ is 11
    return f"{platform.system()} {release}"


def system_info(inp: dict[str, Any]) -> dict[str, Any]:
    from spark_body.fitness.hardware import power, scan

    hw = scan()
    disks = {}
    for root in ("C:\\", "D:\\", "E:\\") if sys.platform == "win32" else ("/",):
        if os.path.exists(root):
            total, _, free = shutil.disk_usage(root)
            disks[root.rstrip("\\")] = {
                "free_gb": round(free / 2**30, 1),
                "total_gb": round(total / 2**30, 1),
            }
    uptime_h = None
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_ulonglong
        uptime_h = round(ctypes.windll.kernel32.GetTickCount64() / 3_600_000, 1)
    return {
        "os": _os_name(),
        "cpu": hw.get("cpu"),
        "cores": hw.get("cores"),
        "ram_gb": hw.get("ram_gb"),
        "disks": disks,
        "uptime_hours": uptime_h,
        "power": power(),
    }


def system_lock(inp: dict[str, Any]) -> dict[str, Any]:
    _windows()
    import ctypes

    if not ctypes.windll.user32.LockWorkStation():
        raise ToolFailure("failed", "Windows didn't lock.")
    return {"locked": True}


def system_sleep(inp: dict[str, Any]) -> dict[str, Any]:
    _windows()
    import ctypes

    # SetSuspendState(hibernate=False, force=False, wake events allowed)
    if not ctypes.windll.powrprof.SetSuspendState(False, False, False):
        raise ToolFailure("failed", "Windows didn't go to sleep.")
    return {"sleeping": True}
