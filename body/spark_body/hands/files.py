"""File tools (REDESIGN §7.3), ported from v1's file_system operations and folder_organize.
Paths may start with a known folder ("Desktop/notes.txt"); on Windows those resolve through the
shell (OneDrive moves Desktop and Documents). Writes and deletes never touch system folders, and
deletes go to the Recycle Bin."""

from __future__ import annotations

import base64
import fnmatch
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from spark_body.hands.errors import ToolFailure

MAX_LIST = 1000
SEARCH_FILES = 20000  # stop walking after this many files
TEXT_SEARCH_BYTES = 2_000_000  # skip bigger files when searching inside them
MANIFEST = ".spark-organize.json"

# FOLDERID_* GUIDs for SHGetKnownFolderPath (they follow OneDrive / user redirection).
_KNOWN = {
    "desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
    "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "pictures": "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
    "music": "{4BD8D571-6D19-48D3-BE97-422220080E43}",
    "videos": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}",
}
CATEGORIES = {
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".svg", ".tif", ".tiff"},
    "Documents": {
        ".pdf",
        ".doc",
        ".docx",
        ".txt",
        ".rtf",
        ".odt",
        ".xls",
        ".xlsx",
        ".csv",
        ".ppt",
        ".pptx",
        ".md",
        ".epub",
    },
    "Videos": {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".webm", ".m4v"},
    "Music": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
    "Installers": {".exe", ".msi", ".msix", ".appx", ".dmg", ".pkg", ".deb", ".apk"},
    "Code": {
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".java",
        ".c",
        ".cpp",
        ".h",
        ".cs",
        ".go",
        ".rs",
        ".rb",
        ".php",
        ".html",
        ".css",
        ".json",
        ".yml",
        ".yaml",
        ".sh",
        ".ps1",
        ".ipynb",
    },
}


def known_folder(name: str) -> Path | None:
    low = name.lower()
    if low == "home":
        return Path.home()
    if low not in _KNOWN:
        return None
    if sys.platform == "win32":
        import ctypes
        import uuid
        from ctypes import wintypes

        guid = (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID(_KNOWN[low]).bytes_le)
        out = ctypes.c_wchar_p()
        shell32 = ctypes.windll.shell32
        shell32.SHGetKnownFolderPath.argtypes = [
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.HANDLE,
            ctypes.POINTER(ctypes.c_wchar_p),
        ]
        if shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(out)) == 0:
            path = Path(out.value or "")
            ctypes.windll.ole32.CoTaskMemFree(out)
            if str(path):
                return path
    return Path.home() / name.capitalize()


def resolve(raw: str) -> Path:
    """'Desktop/notes.txt', '~/x', 'C:/x', or relative to Home."""
    text = raw.strip().strip('"').replace("\\", "/")
    if not text:
        raise ToolFailure("invalid_path", "Give me a path, like Desktop/notes.txt.")
    if text.startswith("~"):
        return Path(os.path.expanduser(text)).resolve()
    first, _, rest = text.partition("/")
    base = known_folder(first)
    if base is not None:
        return (base / rest).resolve() if rest else base.resolve()
    path = Path(text)
    return path.resolve() if path.is_absolute() else (Path.home() / path).resolve()


def _system_dirs() -> list[Path]:
    if sys.platform != "win32":
        return [Path(p) for p in ("/bin", "/boot", "/etc", "/lib", "/sbin", "/usr", "/System")]
    names = ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData")
    return [Path(v).resolve() for n in names if (v := os.environ.get(n))]


def _keep() -> set[Path]:
    return {p.resolve() for n in (*_KNOWN, "home") if (p := known_folder(n)) is not None}


def outside_system(path: Path) -> Path:
    if path.parent == path:
        raise ToolFailure("forbidden", f"I won't change a whole drive ({path}).")
    for root in _system_dirs():
        if path == root or root in path.parents:
            raise ToolFailure("forbidden", f"{path} is a system folder; I don't change those.")
    return path


def guard(path: Path) -> Path:
    """Writes, moves, and deletes stay out of system folders and never hit a drive root or a
    known folder itself (its contents are fine)."""
    if outside_system(path).resolve() in _keep():
        raise ToolFailure(
            "forbidden", f"I won't remove or move {path.name} itself, only what's in it."
        )
    return path


def _entry(p: Path) -> dict[str, Any]:
    st = p.stat()
    return {
        "name": p.name,
        "type": "folder" if p.is_dir() else "file",
        "size": None if p.is_dir() else st.st_size,
        "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="minutes"),
    }


def _shown(p: Path) -> str:
    return str(p).replace("\\", "/")


def file_read(inp: dict[str, Any]) -> dict[str, Any]:
    path = resolve(inp["path"])
    if not path.is_file():
        raise ToolFailure("not_found", f"There's no file at {_shown(path)}.")
    limit = int(inp.get("max_chars", 20000))
    with path.open("r", encoding="utf-8", errors="replace") as f:
        text = f.read(limit + 1)
    return {"path": _shown(path), "text": text[:limit], "truncated": len(text) > limit}


def file_list(inp: dict[str, Any]) -> dict[str, Any]:
    path = resolve(inp["path"])
    if not path.is_dir():
        raise ToolFailure("not_found", f"There's no folder at {_shown(path)}.")
    pattern = str(inp.get("pattern") or "*")
    limit = min(int(inp.get("limit", 200)), MAX_LIST)
    walk = path.rglob(pattern) if inp.get("recursive") else path.glob(pattern)
    items: list[dict[str, Any]] = []
    truncated = False
    for p in sorted(walk, key=lambda q: (not q.is_dir(), str(q).lower())):
        if len(items) >= limit:
            truncated = True
            break
        try:
            entry = _entry(p)
        except OSError:
            continue  # vanished or locked
        if inp.get("recursive"):
            entry["name"] = _shown(p.relative_to(path))
        items.append(entry)
    return {"path": _shown(path), "items": items, "truncated": truncated}


def file_search(inp: dict[str, Any]) -> dict[str, Any]:
    root = resolve(inp["path"])
    if not root.is_dir():
        raise ToolFailure("not_found", f"There's no folder at {_shown(root)}.")
    query = str(inp["query"]).lower()
    limit = int(inp.get("limit", 50))
    matches: list[dict[str, Any]] = []
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "node_modules"]
        for name in filenames:
            seen += 1
            p = Path(dirpath) / name
            hit = query in name.lower()
            if not hit and inp.get("in_content"):
                hit = _contains(p, query)
            if hit:
                matches.append({"path": _shown(p), "name": name})
                if len(matches) >= limit:
                    return {"matches": matches, "truncated": True}
            if seen >= SEARCH_FILES:
                return {"matches": matches, "truncated": True}
    return {"matches": matches, "truncated": False}


def _contains(p: Path, query: str) -> bool:
    try:
        if p.stat().st_size > TEXT_SEARCH_BYTES:
            return False
        return query in p.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False


def file_write(inp: dict[str, Any]) -> dict[str, Any]:
    path = guard(resolve(inp["path"]))
    if path.exists() and not inp.get("overwrite"):
        raise ToolFailure(
            "exists",
            f"{_shown(path)} already exists. Say overwrite to replace it, or pick a new name.",
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    if inp.get("encoding") == "base64":
        try:
            data = base64.b64decode(str(inp["content"]), validate=True)
        except ValueError:
            raise ToolFailure("invalid_input", "That content isn't valid base64.") from None
        path.write_bytes(data)
    else:
        path.write_text(str(inp["content"]), encoding="utf-8")
    return {"path": _shown(path), "bytes": path.stat().st_size}


def file_edit(inp: dict[str, Any]) -> dict[str, Any]:
    path = guard(resolve(inp["path"]))
    if not path.is_file():
        raise ToolFailure("not_found", f"There's no file at {_shown(path)}.")
    text = path.read_text(encoding="utf-8")
    count = text.count(inp["old"])
    if count == 0:
        raise ToolFailure(
            "no_match", "That text isn't in the file. Read it first and copy it exactly."
        )
    if count > 1:
        raise ToolFailure("ambiguous", f"That text appears {count} times. Include more around it.")
    path.write_text(text.replace(inp["old"], inp["new"], 1), encoding="utf-8")
    return {"path": _shown(path), "edited": True}


def file_move(inp: dict[str, Any]) -> dict[str, Any]:
    source = guard(resolve(inp["source"]))
    if not source.exists():
        raise ToolFailure("not_found", f"There's nothing at {_shown(source)}.")
    dest = resolve(inp["destination"])
    if dest.is_dir():
        dest = dest / source.name
    guard(dest)
    if dest.exists():
        raise ToolFailure("exists", f"{_shown(dest)} already exists; pick another name.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(dest))
    return {"from": _shown(source), "to": _shown(dest)}


def _recycle(paths: list[Path]) -> None:
    """To the Recycle Bin (SHFileOperationW, undoable). Elsewhere: a .spark-trash folder."""
    if sys.platform != "win32":
        for p in paths:
            trash = p.parent / ".spark-trash"
            trash.mkdir(exist_ok=True)
            shutil.move(str(p), str(trash / p.name))
        return
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", ctypes.c_ushort),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    fo_delete, allow_undo, no_confirm, silent, no_error_ui = 3, 0x40, 0x10, 0x04, 0x400
    op = SHFILEOPSTRUCTW(
        wFunc=fo_delete,
        pFrom="\0".join(str(p) for p in paths) + "\0\0",
        fFlags=allow_undo | no_confirm | silent | no_error_ui,
    )
    if ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) != 0 or op.fAnyOperationsAborted:
        raise ToolFailure(
            "failed", "Windows wouldn't move those to the Recycle Bin. Is a file open?"
        )


def file_delete(inp: dict[str, Any]) -> dict[str, Any]:
    target = resolve(inp["path"])
    if any(c in target.name for c in "*?["):
        parent = outside_system(target.parent)  # 'Downloads/*' may empty Downloads
        if not parent.is_dir():
            raise ToolFailure("not_found", f"There's no folder at {_shown(parent)}.")
        found = [
            p
            for p in parent.iterdir()
            if fnmatch.fnmatch(p.name.lower(), target.name.lower()) and p.name != MANIFEST
        ]
    else:
        found = [guard(target)] if target.exists() else []
    if not found:
        return {"deleted": 0, "names": []}  # empty is empty
    for p in found:
        guard(p)
    _recycle(found)
    names = sorted(p.name for p in found)
    return {"deleted": len(found), "names": names[:50], "to": "Recycle Bin"}


def file_open(inp: dict[str, Any]) -> dict[str, Any]:
    path = resolve(inp["path"])
    if not path.exists():
        raise ToolFailure("not_found", f"There's nothing at {_shown(path)}.")
    if sys.platform == "win32":
        os.startfile(str(path))  # noqa: S606 (a path the user asked to open)
    return {"opened": _shown(path)}


# ── organize + restore ────────────────────────────────────────────────────────────────────


def _category(p: Path) -> str:
    ext = p.suffix.lower()
    return next((name for name, exts in CATEGORIES.items() if ext in exts), "Other")


def _free(dest: Path) -> Path:
    """'a.pdf' → 'a (2).pdf' when taken."""
    n = 2
    candidate = dest
    while candidate.exists():
        candidate = dest.with_name(f"{dest.stem} ({n}){dest.suffix}")
        n += 1
    return candidate


def _runs(folder: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data.get("runs", []) if isinstance(data, dict) else []


def _save_runs(folder: Path, runs: list[dict[str, Any]]) -> None:
    path = folder / MANIFEST
    if not runs:
        path.unlink(missing_ok=True)
        return
    path.write_text(json.dumps({"runs": runs}, ensure_ascii=False, indent=1), encoding="utf-8")
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x02)  # hidden


def folder_organize(inp: dict[str, Any]) -> dict[str, Any]:
    """Loose files into type folders. Every move and every folder it made is recorded in the
    folder's manifest, so folder_organize_restore can put things back exactly."""
    folder = resolve(inp["path"])
    if not folder.is_dir():
        raise ToolFailure("not_found", f"There's no folder at {_shown(folder)}.")
    outside_system(folder)
    files = [p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")]
    files = [p for p in files if p.name not in (MANIFEST, "desktop.ini")]
    moves: list[dict[str, str]] = []
    created: list[str] = []
    counts: dict[str, int] = {}
    for p in sorted(files):
        name = _category(p)
        target_dir = folder / name
        if not target_dir.exists():
            target_dir.mkdir()
            created.append(name)
        dest = _free(target_dir / p.name)
        os.replace(p, dest)
        moves.append({"from": p.name, "to": _shown(dest.relative_to(folder))})
        counts[name] = counts.get(name, 0) + 1
    if moves:
        runs = _runs(folder)
        runs.append(
            {"at": datetime.now().isoformat(timespec="seconds"), "moves": moves, "created": created}
        )
        _save_runs(folder, runs)
    return {"path": _shown(folder), "moved": counts, "files": len(moves), "new_folders": created}


def folder_organize_restore(inp: dict[str, Any]) -> dict[str, Any]:
    folder = resolve(inp["path"])
    runs = _runs(folder)
    if not runs:
        raise ToolFailure(
            "nothing_to_undo", f"I haven't organized {folder.name} (or it's undone already)."
        )
    run = runs.pop()
    restored, missing = 0, []
    for move in reversed(run["moves"]):
        src = folder / move["to"]
        if not src.exists():
            missing.append(move["from"])
            continue
        os.replace(src, _free(folder / move["from"]))
        restored += 1
    removed = []
    for name in run["created"]:
        d = folder / name
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
            removed.append(name)
    _save_runs(folder, runs)
    return {
        "path": _shown(folder),
        "restored": restored,
        "missing": missing,
        "removed_folders": removed,
    }
