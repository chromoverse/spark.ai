"""Device tools (REDESIGN §5.1, §7.3). Implemented in `body/spark_body/hands/`; the brain only
declares them. QUICK_TOOLS are the reflex's; the agent gets those plus DEVICE_TOOLS. Deterministic
order keeps the prompt cacheable."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.tools.spec import Risk, ToolSpec


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VolumeSet(_In):
    level: int = Field(ge=0, le=100, description="Volume percent, 0-100")


class VolumeChange(_In):
    direction: Literal["up", "down"]
    step: int = Field(default=10, ge=1, le=50, description="Percent to move, default 10")


class VolumeMute(_In):
    mute: bool = Field(description="true mutes, false unmutes")


class MediaControl(_In):
    action: Literal["play", "pause", "toggle", "next", "previous"]


class MediaPlay(_In):
    query: str = Field(max_length=200, description="What to play, in the user's words")
    app: str | None = Field(
        default=None, max_length=60, description="App to play it in, e.g. 'spotify'; omit if unsaid"
    )


class AppOpen(_In):
    app: str = Field(max_length=60, description="App name as the user said it, e.g. 'spotify'")


class BrightnessSet(_In):
    level: int = Field(ge=0, le=100, description="Screen brightness percent, 0-100")


QUICK_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "volume_set",
        "Sets the device volume to a percent.",
        VolumeSet,
        "device",
        Risk.WRITE,
        requires=frozenset({"volume"}),
    ),
    ToolSpec(
        "volume_change",
        "Turns the volume up or down by a step. Use for 'louder', 'turn it down'.",
        VolumeChange,
        "device",
        Risk.WRITE,
        requires=frozenset({"volume"}),
    ),
    ToolSpec(
        "volume_mute",
        "Mutes or unmutes the device.",
        VolumeMute,
        "device",
        Risk.WRITE,
        requires=frozenset({"volume"}),
    ),
    ToolSpec(
        "media_control",
        "Controls whatever media is playing: play (also 'resume'), pause, next, previous. "
        "toggle only when the user doesn't say which.",
        MediaControl,
        "device",
        Risk.WRITE,
        requires=frozenset({"media"}),
    ),
    ToolSpec(
        "media_play",
        "Starts playing something (a song, artist, mood, video) in a media app. 'Open Spotify "
        "and play X' is one media_play call with app set.",
        MediaPlay,
        "device",
        Risk.WRITE,
        requires=frozenset({"media"}),
        timeout_s=8,
    ),
    ToolSpec(
        "app_open",
        "Opens an installed app by the name the user said ('google chrome', or a generic "
        "'browser'); the device resolves it against its installed apps.",
        AppOpen,
        "device",
        Risk.WRITE,
        requires=frozenset({"apps"}),
    ),
    ToolSpec(
        "brightness_set",
        "Sets the screen brightness to a percent.",
        BrightnessSet,
        "device",
        Risk.WRITE,
        requires=frozenset({"brightness"}),
    ),
)


# ── agent device tools (§7.3): files, shell, clipboard, screen, input, apps, system ──────────

PATH_HELP = (
    "Absolute path, or one starting with a known folder: Desktop, Documents, Downloads, "
    "Pictures, Music, Videos, Home (e.g. 'Desktop/notes.txt')"
)


class FileRead(_In):
    path: str = Field(max_length=500, description=PATH_HELP)
    max_chars: int = Field(default=20000, ge=100, le=100000)


class FileText(BaseModel):
    path: str
    text: str
    truncated: bool = False


class FileList(_In):
    path: str = Field(max_length=500, description=PATH_HELP)
    pattern: str = Field(default="*", max_length=100, description="Glob for names, e.g. '*.pdf'")
    recursive: bool = False
    limit: int = Field(default=200, ge=1, le=1000)


class Entry(BaseModel):
    name: str
    type: Literal["file", "folder"]
    size: int | None = None
    modified: str | None = None


class FileEntries(BaseModel):
    path: str
    items: list[Entry]
    truncated: bool = False


class FileSearch(_In):
    path: str = Field(max_length=500, description=PATH_HELP + "; the folder to search under")
    query: str = Field(max_length=200, description="Text to find in file names (or contents)")
    in_content: bool = Field(default=False, description="Also search inside text files")
    limit: int = Field(default=50, ge=1, le=500)


class FileWrite(_In):
    path: str = Field(max_length=500, description=PATH_HELP)
    content: str = Field(max_length=2_000_000)
    encoding: Literal["text", "base64"] = Field(
        default="text", description="base64 for binary content, e.g. an attachment"
    )
    overwrite: bool = Field(default=False, description="Replace the file if it exists")


class FileEdit(_In):
    path: str = Field(max_length=500, description=PATH_HELP)
    old: str = Field(min_length=1, max_length=20000, description="Exact text to replace (once)")
    new: str = Field(max_length=20000)


class FileMove(_In):
    source: str = Field(max_length=500, description=PATH_HELP)
    destination: str = Field(max_length=500, description=PATH_HELP + "; a folder or a new name")


class FileDelete(_In):
    path: str = Field(
        max_length=500,
        description=PATH_HELP + ". A '*' in the last part deletes every match "
        "('Downloads/*' empties Downloads). Goes to the Recycle Bin.",
    )


class PathOnly(_In):
    path: str = Field(max_length=500, description=PATH_HELP)


class ShellRun(_In):
    command: str = Field(max_length=4000, description="One PowerShell command line")
    cwd: str | None = Field(default=None, max_length=500, description=PATH_HELP)
    timeout_s: int = Field(default=30, ge=1, le=120)


class ClipboardWrite(_In):
    text: str = Field(max_length=100000)


class Nothing(_In):
    pass


class KeyboardType(_In):
    text: str = Field(max_length=5000, description="Typed into the window that has focus")


class KeyboardHotkey(_In):
    keys: list[str] = Field(
        min_length=1, max_length=4, description="Pressed together, e.g. ['ctrl', 's']"
    )


class MouseClick(_In):
    x: int = Field(ge=0, le=20000)
    y: int = Field(ge=0, le=20000)
    button: Literal["left", "right"] = "left"
    double: bool = False


class AppName(_In):
    app: str = Field(max_length=60, description="App name as the user said it")


class ProcessList(_In):
    name: str | None = Field(default=None, max_length=60, description="Filter by name")


class ProcessKill(_In):
    name: str = Field(max_length=60, description="Process name, e.g. 'chrome' or 'notepad.exe'")


class SmsSend(_In):
    to: str = Field(max_length=60, description="Contact name or phone number")
    text: str = Field(max_length=1000)


FILES = frozenset({"files"})
INPUT = frozenset({"input"})
DEVICE_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "file_read",
        "Reads a text file and returns its text.",
        FileRead,
        "device",
        Risk.READ,
        requires=FILES,
        output_model=FileText,
        match="path",
        keywords="open show contents text document notes read",
    ),
    ToolSpec(
        "file_list",
        "Lists a folder: names, file or folder, size, modified time.",
        FileList,
        "device",
        Risk.READ,
        requires=FILES,
        output_model=FileEntries,
        match="path",
        keywords="folder directory contents what's in downloads desktop documents list",
    ),
    ToolSpec(
        "file_search",
        "Finds files under a folder by name, or by text inside them.",
        FileSearch,
        "device",
        Risk.READ,
        requires=FILES,
        timeout_s=20,
        match="path",
        keywords="find locate where search grep look for file",
    ),
    ToolSpec(
        "file_write",
        "Creates a text file (or replaces it with overwrite). Parent folders are created.",
        FileWrite,
        "device",
        Risk.WRITE,
        parallel_safe=False,
        requires=FILES,
        match="path",
        review=True,
        confirm="write {path}",
        keywords="create save new file write notes txt document make",
    ),
    ToolSpec(
        "file_edit",
        "Replaces one exact piece of text in a file.",
        FileEdit,
        "device",
        Risk.WRITE,
        parallel_safe=False,
        requires=FILES,
        match="path",
        review=True,
        confirm="edit {path}",
        keywords="change update modify append replace edit file",
    ),
    ToolSpec(
        "file_move",
        "Moves or renames a file or folder.",
        FileMove,
        "device",
        Risk.WRITE,
        parallel_safe=False,
        requires=FILES,
        match="source",
        review=True,
        confirm="move {source} to {destination}",
        keywords="move rename relocate put into folder",
    ),
    ToolSpec(
        "file_delete",
        "Moves files or folders to the Recycle Bin.",
        FileDelete,
        "device",
        Risk.DESTRUCTIVE,
        parallel_safe=False,
        requires=FILES,
        timeout_s=30,
        match="path",
        confirm="delete {path}",
        keywords="delete remove erase trash clean empty clear",
    ),
    ToolSpec(
        "file_open",
        "Opens a file or folder in its default app.",
        PathOnly,
        "device",
        Risk.WRITE,
        requires=FILES,
        match="path",
        keywords="open show launch view file folder",
    ),
    ToolSpec(
        "folder_organize",
        "Sorts a folder's loose files into type folders (Images, Documents, Videos, Music, "
        "Archives, Installers, Code, Other) and keeps a record so folder_organize_restore can "
        "undo it.",
        PathOnly,
        "device",
        Risk.WRITE,
        parallel_safe=False,
        requires=FILES,
        timeout_s=60,
        match="path",
        review=True,
        confirm="organize {path}",
        keywords="organize tidy sort clean up arrange folder downloads desktop",
    ),
    ToolSpec(
        "folder_organize_restore",
        "Undoes the last folder_organize in a folder: files go back, its new folders go away.",
        PathOnly,
        "device",
        Risk.WRITE,
        parallel_safe=False,
        requires=FILES,
        timeout_s=60,
        match="path",
        confirm="undo the organize in {path}",
        keywords="undo restore revert organize put back",
    ),
    ToolSpec(
        "shell_run",
        "Runs one PowerShell command and returns stdout, stderr, and the exit code. Prefer the "
        "file tools for files.",
        ShellRun,
        "device",
        Risk.DESTRUCTIVE,
        parallel_safe=False,
        requires=frozenset({"shell"}),
        timeout_s=125,
        match="command",
        confirm="run {command}",
        keywords="command terminal powershell cmd script install git disk ip network",
    ),
    ToolSpec(
        "clipboard_read",
        "Returns the text on the clipboard.",
        Nothing,
        "device",
        Risk.READ,
        requires=frozenset({"clipboard"}),
        keywords="clipboard copied paste",
    ),
    ToolSpec(
        "clipboard_write",
        "Puts text on the clipboard.",
        ClipboardWrite,
        "device",
        Risk.WRITE,
        requires=frozenset({"clipboard"}),
        keywords="copy clipboard",
    ),
    ToolSpec(
        "screenshot_take",
        "Takes a screenshot of the whole screen and saves it to Pictures/Screenshots.",
        Nothing,
        "device",
        Risk.READ,
        requires=frozenset({"screen"}),
        keywords="screenshot capture screen grab",
    ),
    ToolSpec(
        "keyboard_type",
        "Types text into the window that has focus.",
        KeyboardType,
        "device",
        Risk.WRITE,
        parallel_safe=False,
        requires=INPUT,
        review=True,
        confirm="type into the window that has focus",
        keywords="type keyboard write text enter",
    ),
    ToolSpec(
        "keyboard_hotkey",
        "Presses a key combination, e.g. ctrl+s.",
        KeyboardHotkey,
        "device",
        Risk.WRITE,
        parallel_safe=False,
        requires=INPUT,
        review=True,
        confirm="press {keys}",
        keywords="press key shortcut hotkey ctrl alt",
    ),
    ToolSpec(
        "mouse_click",
        "Clicks at screen coordinates.",
        MouseClick,
        "device",
        Risk.WRITE,
        parallel_safe=False,
        requires=INPUT,
        review=True,
        confirm="click at {x},{y}",
        keywords="click mouse tap press button",
    ),
    ToolSpec(
        "app_list",
        "Lists the installed apps this device can open.",
        Nothing,
        "device",
        Risk.READ,
        requires=frozenset({"apps"}),
        keywords="installed apps programs which",
    ),
    ToolSpec(
        "app_close",
        "Closes an app's windows (asks it to quit, like clicking X).",
        AppName,
        "device",
        Risk.WRITE,
        requires=frozenset({"apps"}),
        match="app",
        review=True,
        confirm="close {app}",
        keywords="close quit exit app window",
    ),
    ToolSpec(
        "process_list",
        "Lists running processes with memory use.",
        ProcessList,
        "device",
        Risk.READ,
        requires=frozenset({"processes"}),
        keywords="running processes memory cpu task manager what's running",
    ),
    ToolSpec(
        "process_kill",
        "Force-closes a process by name (unsaved work is lost).",
        ProcessKill,
        "device",
        Risk.DESTRUCTIVE,
        requires=frozenset({"processes"}),
        match="name",
        confirm="force-close {name}",
        keywords="kill force close end task frozen stuck process",
    ),
    ToolSpec(
        "system_info",
        "Returns OS, CPU, memory, disk space, uptime, and battery.",
        Nothing,
        "device",
        Risk.READ,
        requires=frozenset({"system"}),
        keywords="system specs disk space storage memory ram cpu uptime battery",
    ),
    ToolSpec(
        "system_lock",
        "Locks the screen.",
        Nothing,
        "device",
        Risk.WRITE,
        requires=frozenset({"power"}),
        keywords="lock screen computer",
    ),
    ToolSpec(
        "system_sleep",
        "Puts the device to sleep.",
        Nothing,
        "device",
        Risk.WRITE,
        requires=frozenset({"power"}),
        review=True,
        confirm="put this device to sleep",
        keywords="sleep suspend standby",
    ),
    ToolSpec(
        "sms_send",
        "Sends a text message from a phone.",
        SmsSend,
        "device",
        Risk.EXTERNAL,
        requires=frozenset({"sms"}),
        timeout_s=15,
        match="to",
        confirm="text {to}: {text}",
        keywords="sms text message send",
    ),
)
