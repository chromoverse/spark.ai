"""
FileSearcher — Deep, cross-platform file finder.
Searches hidden files, system dirs, all drives, with smart prioritisation.

Usage:
    fs = FileSearcher()
    results = fs.search("hey.txt")
    results = fs.search("report.pdf")
    results = fs.search(".env")       # hidden dot-file
    results = fs.search("*.png")      # extension wildcard
"""

from __future__ import annotations

import fnmatch
import logging
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Priority search roots (fast, common) ──────────────────────────────────────
_WIN_PRIORITY_DIRS = [
    Path.home() / "Desktop",
    Path.home() / "Documents",
    Path.home() / "Downloads",
    Path.home() / "Pictures",
    Path.home() / "Videos",
    Path.home() / "Music",
    Path.home() / "OneDrive",
    Path.home() / "AppData" / "Roaming",
    Path.home() / "AppData" / "Local",
    Path("C:/Users/Public"),
]
_MAC_PRIORITY_DIRS = [
    Path.home() / "Desktop",
    Path.home() / "Documents",
    Path.home() / "Downloads",
    Path.home() / "Pictures",
    Path.home() / "Movies",
    Path.home() / "Music",
    Path("/Users/Shared"),
]
_LINUX_PRIORITY_DIRS = [
    Path.home(),
    Path.home() / "Desktop",
    Path.home() / "Documents",
    Path.home() / "Downloads",
    Path.home() / "Pictures",
    Path.home() / "Videos",
    Path("/etc"),
    Path("/var"),
]


class FileSearcher:
    """
    Finds files by name/pattern across the entire file system,
    including hidden and system files.

    Priority order
    ──────────────
    1. Platform fast-search (PowerShell / mdfind / find)
    2. Common user directories (Python walk, fast)
    3. Full drive / filesystem scan (Python walk, thorough)
    """

    _RESULT_LIMIT = 200  # cap results to avoid flooding

    def __init__(self):
        self._os = sys.platform

    # ─────────────────────────────────────────────────────────────────────────
    #  Public
    # ─────────────────────────────────────────────────────────────────────────
    def search(self, query: str,
               search_paths: Optional[List[str]] = None,
               deep: bool = True) -> List[Dict]:
        """
        Search for files matching *query*.

        Args:
            query:        Filename, pattern (``*.png``), or partial name.
            search_paths: Override default scan roots.
            deep:         If True, scan entire filesystem after priority dirs.

        Returns:
            List of dicts with ``name``, ``path``, ``size``, ``modified``,
            ``hidden``, ``extension``.  Empty list if nothing found.
        """
        query = query.strip()
        if not query:
            return []

        logger.info("[FileSearcher] query='%s' deep=%s", query, deep)

        found: Dict[str, Dict] = {}  # path → info (dedup)

        # ── 1. Fast native search ────────────────────────────────────────────
        native = self._native_search(query)
        for r in native:
            found[r["path"]] = r
        if found:
            logger.info("[FileSearcher] native search got %d hits", len(found))

        # ── 2. Priority directories ──────────────────────────────────────────
        roots = search_paths or self._priority_roots()
        for root in roots:
            if len(found) >= self._RESULT_LIMIT:
                break
            self._walk_for_files(str(root), query, found)

        # ── 3. Full scan (if deep and still under limit) ─────────────────────
        if deep and len(found) < self._RESULT_LIMIT:
            for drive_root in self._all_roots():
                if str(drive_root) in [str(r) for r in roots]:
                    continue  # already searched
                if len(found) >= self._RESULT_LIMIT:
                    break
                self._walk_for_files(str(drive_root), query, found,
                                     max_depth=20, include_hidden=True)

        results = sorted(found.values(), key=lambda x: x["name"].lower())
        logger.info("[FileSearcher] total=%d results for '%s'", len(results), query)
        return results

    # ─────────────────────────────────────────────────────────────────────────
    #  Native fast-search per platform
    # ─────────────────────────────────────────────────────────────────────────
    def _native_search(self, query: str) -> List[Dict]:
        try:
            if self._os == "win32":
                return self._win_search(query)
            elif self._os == "darwin":
                return self._mac_search(query)
            else:
                return self._linux_search(query)
        except Exception as e:
            logger.debug("[FileSearcher] native search error: %s", e)
            return []

    def _win_search(self, query: str) -> List[Dict]:
        """
        Use PowerShell Get-ChildItem with -Force (shows hidden + system)
        across all available drives.
        """
        drives = self._win_drives()
        pattern = query if ("*" in query or "?" in query) else f"*{query}*"
        results = []
        for drive in drives:
            try:
                ps = (
                    f"Get-ChildItem -Path '{drive}' -Recurse -Force "
                    f"-Filter '{pattern}' -File "
                    f"-ErrorAction SilentlyContinue "
                    f"| Select-Object -First 200 "
                    f"| ForEach-Object {{ $_.FullName + '|' + $_.Length + '|' + $_.LastWriteTime }}"
                )
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps],
                    capture_output=True, text=True, timeout=30,
                )
                for line in (r.stdout or "").splitlines():
                    parts = line.strip().split("|")
                    if len(parts) >= 1 and parts[0]:
                        fp = parts[0]
                        size = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
                        results.append(self._make_result(fp, size))
            except Exception as e:
                logger.debug("[FileSearcher] win drive %s error: %s", drive, e)
        return results

    def _mac_search(self, query: str) -> List[Dict]:
        """Use mdfind + find for thorough macOS file search."""
        results = []
        # mdfind (Spotlight) — fast
        clean = query.replace("*", "").replace("?", "")
        try:
            r = subprocess.run(
                ["mdfind", "-name", clean],
                capture_output=True, text=True, timeout=10,
            )
            for line in r.stdout.splitlines():
                if line and os.path.isfile(line):
                    if self._matches_query(os.path.basename(line), query):
                        results.append(self._make_result(line))
        except Exception:
            pass
        # find hidden too
        try:
            r2 = subprocess.run(
                ["find", "/", "-name", query, "-not", "-path", "*/proc/*"],
                capture_output=True, text=True, timeout=15,
            )
            for line in r2.stdout.splitlines():
                if line and os.path.isfile(line):
                    results.append(self._make_result(line))
        except Exception:
            pass
        return results

    def _linux_search(self, query: str) -> List[Dict]:
        """Use find across the whole filesystem."""
        results = []
        pattern = query if ("*" in query or "?" in query) else f"*{query}*"
        try:
            r = subprocess.run(
                ["find", "/", "-name", pattern, "-not", "-path", "*/proc/*",
                 "-not", "-path", "*/sys/*"],
                capture_output=True, text=True, timeout=20,
            )
            for line in r.stdout.splitlines():
                if line and os.path.isfile(line):
                    results.append(self._make_result(line))
        except Exception as e:
            logger.debug("[FileSearcher] linux find: %s", e)
        return results

    # ─────────────────────────────────────────────────────────────────────────
    #  Python fallback walk
    # ─────────────────────────────────────────────────────────────────────────
    def _walk_for_files(self, root: str, query: str,
                        found: Dict[str, Dict],
                        max_depth: int = 10,
                        include_hidden: bool = True):
        if not os.path.isdir(root):
            return
        try:
            for dirpath, dirs, files in os.walk(root, followlinks=False):
                depth = dirpath[len(root):].count(os.sep)
                if depth >= max_depth:
                    dirs[:] = []
                    continue

                # Optionally prune hidden dirs to save time (still scan files)
                if not include_hidden:
                    dirs[:] = [d for d in dirs if not d.startswith(".")]

                for fname in files:
                    if self._matches_query(fname, query):
                        fp = os.path.join(dirpath, fname)
                        if fp not in found:
                            found[fp] = self._make_result(fp)
                        if len(found) >= self._RESULT_LIMIT:
                            return
        except PermissionError:
            pass
        except Exception as e:
            logger.debug("[FileSearcher] walk %s: %s", root, e)

    # ─────────────────────────────────────────────────────────────────────────
    #  Helpers
    # ─────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _matches_query(fname: str, query: str) -> bool:
        """Support exact, wildcard, and substring matching."""
        fl = fname.lower()
        ql = query.lower()
        if "*" in ql or "?" in ql:
            return fnmatch.fnmatch(fl, ql)
        return ql in fl  # substring match (covers exact too)

    @staticmethod
    def _make_result(path: str, size: int = -1) -> Dict:
        try:
            stat = os.stat(path)
            if size < 0:
                size = stat.st_size
            modified = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
        except Exception:
            modified = "unknown"
        fname = os.path.basename(path)
        is_hidden = fname.startswith(".") or _win_is_hidden(path)
        _, ext = os.path.splitext(fname)
        return {
            "name":      fname,
            "path":      path,
            "size":      size,
            "modified":  modified,
            "hidden":    is_hidden,
            "extension": ext.lower(),
            "type":      "file",
        }

    def _priority_roots(self) -> List[Path]:
        if self._os == "win32":
            return [p for p in _WIN_PRIORITY_DIRS if p.exists()]
        elif self._os == "darwin":
            return [p for p in _MAC_PRIORITY_DIRS if p.exists()]
        else:
            return [p for p in _LINUX_PRIORITY_DIRS if p.exists()]

    def _all_roots(self) -> List[Path]:
        if self._os == "win32":
            return [Path(f"{d}:\\") for d in "CDEFGHIJKLMNOPQRSTUVWXYZ"
                    if Path(f"{d}:\\").exists()]
        elif self._os == "darwin":
            return [Path("/")]
        else:
            return [Path("/")]

    @staticmethod
    def _win_drives() -> List[str]:
        import string
        return [f"{d}:\\" for d in string.ascii_uppercase
                if os.path.exists(f"{d}:\\")]


# ─────────────────────────────────────────────────────────────────────────────
#  Windows hidden attribute helper
# ─────────────────────────────────────────────────────────────────────────────
def _win_is_hidden(path: str) -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        attrs = ctypes.windll.kernel32.GetFileAttributesW(path)
        return bool(attrs != -1 and attrs & 2)  # FILE_ATTRIBUTE_HIDDEN = 2
    except Exception:
        return False