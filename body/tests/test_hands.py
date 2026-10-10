"""Desktop hands ported from v1 (PHASES R2): one test per tool. Files run for real in a temp
folder (known folders point there); OS calls that would move the user's mouse, lock the screen, or
kill processes are faked at their edge. # proves §7.3, API.md §3.3"""

from __future__ import annotations

import base64
import ctypes
import sys
from pathlib import Path
from typing import Any

import pytest

from spark_body import hands
from spark_body.hands import apps, desktop, files, shell
from spark_body.hands.errors import ToolFailure

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows API")


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Desktop, Downloads, … live under tmp_path; deletes go to tmp_path/trash."""
    for name in ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos"):
        (tmp_path / name).mkdir()

    def known(name: str) -> Path | None:
        if name.lower() == "home":
            return tmp_path
        names = ("desktop", "documents", "downloads", "pictures", "music", "videos")
        return tmp_path / name.capitalize() if name.lower() in names else None

    trash = tmp_path / "trash"
    trash.mkdir()

    def recycle(paths: list[Path]) -> None:
        for p in paths:
            p.rename(trash / p.name)

    monkeypatch.setattr(files, "known_folder", known)
    monkeypatch.setattr(files, "_recycle", recycle)
    return tmp_path


def test_file_write_read_edit(home: Path) -> None:
    out = files.file_write({"path": "Desktop/notes.txt", "content": "- buy milk\n- call mom\n"})
    assert out["path"].endswith("Desktop/notes.txt") and out["bytes"] > 0
    with pytest.raises(ToolFailure) as exc:
        files.file_write({"path": "Desktop/notes.txt", "content": "x"})
    assert exc.value.code == "exists"
    files.file_edit({"path": "Desktop/notes.txt", "old": "call mom", "new": "call dad"})
    read = files.file_read({"path": "desktop\\notes.txt", "max_chars": 100})
    assert read["text"] == "- buy milk\n- call dad\n" and read["truncated"] is False
    with pytest.raises(ToolFailure) as exc:
        files.file_edit({"path": "Desktop/notes.txt", "old": "nope", "new": "x"})
    assert exc.value.code == "no_match"
    assert files.file_read({"path": "Desktop/notes.txt", "max_chars": 100})["text"].count("-") == 2


def test_file_write_base64_for_attachments(home: Path) -> None:
    data = b"%PDF-1.4 binary \x00\xff"
    files.file_write(
        {
            "path": "Downloads/INV-2041.pdf",
            "content": base64.b64encode(data).decode(),
            "encoding": "base64",
        }
    )
    assert (home / "Downloads" / "INV-2041.pdf").read_bytes() == data
    with pytest.raises(ToolFailure):
        files.file_write(
            {"path": "Downloads/bad.pdf", "content": "not base64!!", "encoding": "base64"}
        )


def test_file_list_and_search(home: Path) -> None:
    (home / "Documents" / "Taxes").mkdir()
    (home / "Documents" / "Taxes" / "tax-2025.pdf").write_text("refund")
    (home / "Documents" / "notes.txt").write_text("my tax id is here")
    listed = files.file_list({"path": "Documents"})
    assert [(i["name"], i["type"]) for i in listed["items"]] == [
        ("Taxes", "folder"),
        ("notes.txt", "file"),
    ]
    deep = files.file_list({"path": "Documents", "pattern": "*.pdf", "recursive": True})
    assert [i["name"] for i in deep["items"]] == ["Taxes/tax-2025.pdf"]
    by_name = files.file_search({"path": "Documents", "query": "TAX"})
    assert [m["name"] for m in by_name["matches"]] == ["tax-2025.pdf"]
    inside = files.file_search({"path": "Documents", "query": "tax id", "in_content": True})
    assert [m["name"] for m in inside["matches"]] == ["notes.txt"]
    with pytest.raises(ToolFailure):
        files.file_list({"path": "Documents/nope"})


def test_file_move(home: Path) -> None:
    (home / "Downloads" / "a.pdf").write_text("a")
    out = files.file_move({"source": "Downloads/a.pdf", "destination": "Documents"})
    assert out["to"].endswith("Documents/a.pdf") and (home / "Documents" / "a.pdf").exists()


def test_file_delete_empties_a_folder_into_the_recycle_bin(home: Path) -> None:
    for name in ("a.zip", "b.exe", "c.pdf"):
        (home / "Downloads" / name).write_text(name)
    out = files.file_delete({"path": "Downloads/*"})
    assert (out["deleted"], out["names"]) == (3, ["a.zip", "b.exe", "c.pdf"])
    assert sorted(p.name for p in (home / "trash").iterdir()) == ["a.zip", "b.exe", "c.pdf"]
    assert (home / "Downloads").is_dir()  # emptied, not removed
    assert files.file_delete({"path": "Downloads/*"}) == {
        "deleted": 0,
        "names": [],
    }  # empty is empty


def test_guards_keep_known_folders_and_system_folders_safe(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ToolFailure) as exc:
        files.file_delete({"path": "Downloads"})
    assert exc.value.code == "forbidden"
    with pytest.raises(ToolFailure):
        files.file_delete({"path": "Home/*"})  # would take Desktop, Documents, …
    system = home / "Windows"
    system.mkdir()
    monkeypatch.setenv("SystemRoot", str(system))
    monkeypatch.setattr(files, "_system_dirs", lambda: [system.resolve()])
    with pytest.raises(ToolFailure) as exc:
        files.file_write({"path": str(system / "evil.dll"), "content": "x"})
    assert exc.value.code == "forbidden"


def test_file_open(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(files.os, "startfile", opened.append, raising=False)
    (home / "Desktop" / "notes.txt").write_text("x")
    out = files.file_open({"path": "Desktop/notes.txt"})
    assert out["opened"].endswith("Desktop/notes.txt")
    assert opened == (
        [str((home / "Desktop" / "notes.txt").resolve())] if sys.platform == "win32" else []
    )


def test_folder_organize_and_restore(home: Path) -> None:
    """The promises of v1's restore test: special and unicode names survive, folders that existed
    before stay, folders this run made go away."""
    dl = home / "Downloads"
    (dl / "Images").mkdir()  # already there
    names = ["photo & one (100%).jpg", "résumé café é.pdf", "setup.exe", "song.mp3", "weird.xyz"]
    for name in names:
        (dl / name).write_text(name)
    (dl / "Images" / "photo & one (100%).jpg").write_text("older one")  # a name clash
    out = files.folder_organize({"path": "Downloads"})
    assert out["moved"] == {"Images": 1, "Documents": 1, "Installers": 1, "Music": 1, "Other": 1}
    assert sorted(out["new_folders"]) == ["Documents", "Installers", "Music", "Other"]
    assert (dl / "Images" / "photo & one (100%) (2).jpg").read_text() == "photo & one (100%).jpg"
    assert not [p for p in dl.iterdir() if p.is_file() and not p.name.startswith(".")]

    back = files.folder_organize_restore({"path": "Downloads"})
    assert (back["restored"], back["missing"]) == (5, [])
    assert sorted(p.name for p in dl.iterdir() if not p.name.startswith(".")) == sorted(
        [*names, "Images"]
    )
    assert (dl / "Images" / "photo & one (100%).jpg").read_text() == "older one"  # untouched
    assert not (dl / files.MANIFEST).exists()
    with pytest.raises(ToolFailure) as exc:
        files.folder_organize_restore({"path": "Downloads"})
    assert exc.value.code == "nothing_to_undo"


def test_shell_run() -> None:
    hello = "Write-Output hi" if sys.platform == "win32" else "echo hi"
    out = shell.shell_run({"command": hello, "timeout_s": 30})
    assert (out["exit_code"], out["stdout"].strip()) == (0, "hi")
    fail = shell.shell_run({"command": "exit 3", "timeout_s": 30})
    assert fail["exit_code"] == 3
    slow = "Start-Sleep 5" if sys.platform == "win32" else "sleep 5"
    with pytest.raises(ToolFailure) as exc:
        shell.shell_run({"command": slow, "timeout_s": 1})
    assert exc.value.code == "timeout"


def test_clipboard_read_and_write(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, str | None]] = []

    def ps(script: str, stdin: str | None = None, timeout: float = 15) -> str:
        seen.append((script, stdin))
        return "copied text\r\n"

    monkeypatch.setattr(desktop, "_ps", ps)
    assert desktop.clipboard_write({"text": 'it\'s "quoted" & safe'}) == {"copied": 20}
    assert seen[0][1] == 'it\'s "quoted" & safe'  # user text goes through stdin, never the script
    assert desktop.clipboard_read({}) == {"text": "copied text"}


def test_screenshot_take_saves_to_pictures(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str | None] = []
    monkeypatch.setattr(desktop, "known_folder", files.known_folder)
    monkeypatch.setattr(
        desktop, "_ps", lambda script, stdin=None, timeout=15: seen.append(stdin) or "1920x1080\n"
    )
    out = desktop.screenshot_take({})
    assert out["size"] == "1920x1080" and "/Pictures/Screenshots/Spark " in out["path"]
    assert seen[0] is not None and seen[0].endswith(".png")


def test_keyboard_type_and_hotkey(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[int, int, int]] = []
    monkeypatch.setattr(desktop, "_send", sent.extend)
    desktop.keyboard_type({"text": "hi\n😀"})
    unicode_codes = [s for v, s, f in sent if f == desktop._UNICODE]
    assert unicode_codes == [ord("h"), ord("i"), 0xD83D, 0xDE00]  # the emoji as a surrogate pair
    assert (desktop.VK["enter"], 0, 0) in sent
    sent.clear()
    assert desktop.keyboard_hotkey({"keys": ["Ctrl", "s"]}) == {"pressed": "ctrl+s"}
    assert sent == [(0x11, 0, 0), (0x53, 0, 0), (0x53, 0, 2), (0x11, 0, 2)]
    with pytest.raises(ToolFailure):
        desktop.keyboard_hotkey({"keys": ["hyper"]})


@windows_only
def test_mouse_click(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    monkeypatch.setattr(user32, "SetCursorPos", lambda x, y: calls.append(("move", x, y)) or 1)
    monkeypatch.setattr(user32, "mouse_event", lambda flag, *_: calls.append(flag))
    out = desktop.mouse_click({"x": 10, "y": 20, "button": "right", "double": True})
    assert out == {"clicked": [10, 20], "button": "right"}
    assert calls == [("move", 10, 20), 0x0008, 0x0010, 0x0008, 0x0010]


class _Done:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self.stdout = ""


def test_processes_list_kill_and_app_close(monkeypatch: pytest.MonkeyPatch) -> None:
    tasks = [
        {"name": "chrome.exe", "pid": 1, "memory_mb": 300},
        {"name": "chrome.exe", "pid": 2, "memory_mb": 200},
        {"name": "Spotify.exe", "pid": 3, "memory_mb": 150},
    ]
    monkeypatch.setattr(desktop, "_tasks", lambda: list(tasks))
    ran: list[list[str]] = []
    monkeypatch.setattr(desktop.subprocess, "run", lambda argv, **_: ran.append(argv) or _Done())
    monkeypatch.setattr(desktop.time, "sleep", lambda s: None)
    out = desktop.process_list({})
    assert out["processes"][0] == {"name": "chrome.exe", "count": 2, "memory_mb": 500}
    assert desktop.process_kill({"name": "Chrome"}) == {"closed": "chrome.exe"}
    assert ran[-1] == ["taskkill", "/F", "/IM", "chrome.exe"]
    closed = desktop.app_close({"app": "spotify"})
    assert closed["closed"] == "Spotify.exe" and ran[-1] == [
        "taskkill",
        "/IM",
        "Spotify.exe",
    ]  # no /F
    with pytest.raises(ToolFailure) as exc:
        desktop.process_kill({"name": "photoshop"})
    assert exc.value.code == "not_running"


def test_app_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        apps.INDEX,
        "entries",
        {"spotify": ("Spotify", "a"), "vlc": ("VLC media player", "b"), "s": ("Spotify", "a")},
    )
    assert apps.app_list({}) == {"apps": ["Spotify", "VLC media player"], "total": 2}


def test_system_info() -> None:
    out = desktop.system_info({})
    assert out["os"] and out["cores"] and out["disks"]
    assert "plugged" in out["power"]


@windows_only
def test_system_lock_and_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []
    monkeypatch.setattr(ctypes.windll.user32, "LockWorkStation", lambda: called.append("lock") or 1)  # type: ignore[attr-defined]
    monkeypatch.setattr(
        ctypes.windll.powrprof, "SetSuspendState", lambda *a: called.append("sleep") or 1
    )  # type: ignore[attr-defined]
    assert desktop.system_lock({}) == {"locked": True}
    assert desktop.system_sleep({}) == {"sleeping": True}
    assert called == ["lock", "sleep"]


async def test_run_turns_os_errors_into_actionable_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def denied(inp: dict[str, Any]) -> dict[str, Any]:
        raise PermissionError(13, "Access is denied", "C:/secret.txt")

    def broken(inp: dict[str, Any]) -> dict[str, Any]:
        raise ValueError("boom")

    monkeypatch.setitem(hands.HANDS, "file_read", denied)
    monkeypatch.setitem(hands.HANDS, "file_list", broken)
    with pytest.raises(ToolFailure) as exc:
        await hands.run("file_read", {})
    assert (exc.value.code, exc.value.message) == (
        "denied",
        "Windows won't let me touch C:/secret.txt (permission denied).",
    )
    with pytest.raises(ToolFailure) as exc:
        await hands.run("file_list", {})
    assert exc.value.code == "failed" and "boom" not in exc.value.message  # no raw errors


def test_every_brain_device_tool_has_a_hand() -> None:
    """The brain's catalog (brain/app/tools/device_specs.py) and the body agree on names. The phone
    tool sms_send belongs to the mobile body."""
    declared = {
        "volume_set", "volume_change", "volume_mute", "media_control", "media_play", "app_open",
        "brightness_set", "file_read", "file_list", "file_search", "file_write", "file_edit",
        "file_move", "file_delete", "file_open", "folder_organize", "folder_organize_restore",
        "shell_run", "clipboard_read", "clipboard_write", "screenshot_take", "keyboard_type",
        "keyboard_hotkey", "mouse_click", "app_list", "app_close", "process_list", "process_kill",
        "system_info", "system_lock", "system_sleep",
    }  # fmt: skip
    assert declared <= set(hands.HANDS)
    caps = set(hands.CAPABILITIES)
    assert {"files", "shell", "system"} <= caps
