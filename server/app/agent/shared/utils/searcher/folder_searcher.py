"""
FolderSearcher — Deep, cross-platform directory finder.
Searches hidden, system, and all-drive directories.

Usage:
    fs = FolderSearcher()
    results = fs.search("downloads")
    results = fs.search("node_modules")
    results = fs.search(".git")          # hidden folder
    results = fs.search("my project")   # fuzzy
"""

from __future__ import annotations

import fnmatch
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class FolderSearcher:
    """
    Finds directories by name/pattern across the entire file system,
    including hidden and system directories.

    Priority order
    ──────────────
    1. Platform fast-search (PowerShell / find)
    2. Common user directories
    3. Full filesystem scan
    """

    _RESULT_LIMIT = 150

    def __init__(self):
        self._os = sys.platform

    # ─────────────────────────────────────────────────────────────────────────
    #  Public
    # ─────────────────────────────────────────────────────────────────────────
    def search(self, query: str,
               search_paths: Optional[List[str]] = None,
               deep: bool = True) -> List[Dict]:
        """
        Search for directories matching *query*.

        Args:
            query:        Folder name, glob pattern, or partial name.
            search_paths: Override default scan roots.
            deep:         If True, scan full filesystem after priority paths.

        Returns:
            List of dicts with ``name``, ``path``, ``modified``, ``hidden``,
            ``item_count``.  Empty list if nothing found.
        """
        query = query.strip()
        if not query:
            return []

        logger.info("[FolderSearcher] query='%s' deep=%s", query, deep)

        found: Dict[str, Dict] = {}

        # ── 1. Native search ─────────────────────────────────────────────────
        for r in self._native_search(query):
            found[r["path"]] = r

        # ── 2. Priority dirs ─────────────────────────────────────────────────
        roots = search_paths or self._priority_roots()
        for root in roots:
            if len(found) >= self._RESULT_LIMIT:
                break
            self._walk_for_dirs(str(root), query, found)

        # ── 3. Deep full scan ─────────────────────────────────────────────────
        if deep and len(found) < self._RESULT_LIMIT:
            for drive_root in self._all_roots():
                if str(drive_root) in [str(r) for r in roots]:
                    continue
                if len(found) >= self._RESULT_LIMIT:
                    break
                self._walk_for_dirs(str(drive_root), query, found,
                                    max_depth=20, include_hidden=True)

        results = sorted(found.values(), key=lambda x: x["name"].lower())
        logger.info("[FolderSearcher] found %d dirs for '%s'", len(results), query)
        return results

    # ─────────────────────────────────────────────────────────────────────────
    #  Native fast-search
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
            logger.debug("[FolderSearcher] native error: %s", e)
            return []

    def _win_search(self, query: str) -> List[Dict]:
        """PowerShell Get-ChildItem -Directory -Force across all drives."""
        drives  = self._win_drives()
        pattern = query if ("*" in query or "?" in query) else f"*{query}*"
        results = []
        for drive in drives:
            try:
                ps = (
                    f"Get-ChildItem -Path '{drive}' -Recurse -Force "
                    f"-Filter '{pattern}' -Directory "
                    f"-ErrorAction SilentlyContinue "
                    f"| Select-Object -First 150 "
                    f"| ForEach-Object {{ $_.FullName + '|' + $_.LastWriteTime }}"
                )
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps],
                    capture_output=True, text=True, timeout=30,
                )
                for line in (r.stdout or "").splitlines():
                    parts = line.strip().split("|")
                    if parts and parts[0] and os.path.isdir(parts[0]):
                        results.append(self._make_result(parts[0]))
            except Exception as e:
                logger.debug("[FolderSearcher] drive %s: %s", drive, e)
        return results

    def _mac_search(self, query: str) -> List[Dict]:
        results = []
        clean = query.replace("*", "").replace("?", "")
        # mdfind for folders
        try:
            r = subprocess.run(
                ["mdfind", "-name", clean],
                capture_output=True, text=True, timeout=10,
            )
            for line in r.stdout.splitlines():
                if line and os.path.isdir(line):
                    if self._matches_query(os.path.basename(line), query):
                        results.append(self._make_result(line))
        except Exception:
            pass
        # find -type d
        try:
            r2 = subprocess.run(
                ["find", "/", "-type", "d", "-name", query,
                 "-not", "-path", "*/proc/*"],
                capture_output=True, text=True, timeout=15,
            )
            for line in r2.stdout.splitlines():
                if line and os.path.isdir(line):
                    results.append(self._make_result(line))
        except Exception:
            pass
        return results

    def _linux_search(self, query: str) -> List[Dict]:
        pattern = query if ("*" in query or "?" in query) else f"*{query}*"
        results = []
        try:
            r = subprocess.run(
                ["find", "/", "-type", "d", "-name", pattern,
                 "-not", "-path", "*/proc/*",
                 "-not", "-path", "*/sys/*"],
                capture_output=True, text=True, timeout=20,
            )
            for line in r.stdout.splitlines():
                if line and os.path.isdir(line):
                    results.append(self._make_result(line))
        except Exception as e:
            logger.debug("[FolderSearcher] linux find: %s", e)
        return results

    # ─────────────────────────────────────────────────────────────────────────
    #  Python fallback walk
    # ─────────────────────────────────────────────────────────────────────────
    def _walk_for_dirs(self, root: str, query: str,
                       found: Dict[str, Dict],
                       max_depth: int = 10,
                       include_hidden: bool = True):
        if not os.path.isdir(root):
            return
        try:
            for dirpath, dirs, _ in os.walk(root, followlinks=False):
                depth = dirpath[len(root):].count(os.sep)
                if depth >= max_depth:
                    dirs[:] = []
                    continue

                to_visit = list(dirs)
                if not include_hidden:
                    to_visit = [d for d in dirs if not d.startswith(".")]
                dirs[:] = to_visit  # control recursion

                for dname in dirs:
                    if self._matches_query(dname, query):
                        fp = os.path.join(dirpath, dname)
                        if fp not in found:
                            found[fp] = self._make_result(fp)
                        if len(found) >= self._RESULT_LIMIT:
                            return
        except PermissionError:
            pass
        except Exception as e:
            logger.debug("[FolderSearcher] walk %s: %s", root, e)

    # ─────────────────────────────────────────────────────────────────────────
    #  Helpers
    # ─────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _matches_query(name: str, query: str) -> bool:
        nl = name.lower()
        ql = query.lower()
        if "*" in ql or "?" in ql:
            return fnmatch.fnmatch(nl, ql)
        return ql in nl

    @staticmethod
    def _make_result(path: str) -> Dict:
        fname = os.path.basename(path) or path
        try:
            stat = os.stat(path)
            modified = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
        except Exception:
            modified = "unknown"

        is_hidden = fname.startswith(".")
        if sys.platform == "win32":
            try:
                import ctypes
                attrs = ctypes.windll.kernel32.GetFileAttributesW(path)
                if attrs != -1 and (attrs & 2):
                    is_hidden = True
            except Exception:
                pass

        # Count immediate children (best-effort)
        try:
            item_count = len(os.listdir(path))
        except Exception:
            item_count = -1

        return {
            "name":       fname,
            "path":       path,
            "modified":   modified,
            "hidden":     is_hidden,
            "item_count": item_count,
            "type":       "folder",
        }

    def _priority_roots(self) -> List[Path]:
        if self._os == "win32":
            candidates = [
                Path.home(),
                Path.home() / "Desktop",
                Path.home() / "Documents",
                Path.home() / "Downloads",
                Path.home() / "AppData" / "Local",
                Path.home() / "AppData" / "Roaming",
                Path("C:/Program Files"),
                Path("C:/Program Files (x86)"),
                Path("C:/Users/Public"),
            ]
        elif self._os == "darwin":
            candidates = [
                Path.home(),
                Path("/Applications"),
                Path("/Library"),
                Path("/usr"),
                Path("/opt"),
            ]
        else:
            candidates = [
                Path.home(),
                Path("/etc"),
                Path("/var"),
                Path("/usr"),
                Path("/opt"),
            ]
        return [p for p in candidates if p.exists()]

    def _all_roots(self) -> List[Path]:
        if self._os == "win32":
            return [Path(f"{d}:\\") for d in "CDEFGHIJKLMNOPQRSTUVWXYZ"
                    if Path(f"{d}:\\").exists()]
        return [Path("/")]

    @staticmethod
    def _win_drives() -> List[str]:
        import string
        return [f"{d}:\\" for d in string.ascii_uppercase
                if os.path.exists(f"{d}:\\")]