"""
SystemSearcher — Unified public API for system-wide search.

Three clean public methods:
    search_app(query)     → find any app, system tool, or website
    search_files(query)   → find files by name/pattern anywhere on disk
    search_folders(query) → find directories by name anywhere on disk

Examples
────────
    from searcher.system_searcher import SystemSearcher

    ss = SystemSearcher()

    # Apps / tools / websites
    ss.search_app("event viewer")        # → MMC snap-in
    ss.search_app("flush dns")           # → ipconfig command
    ss.search_app("ms-settings:network") # → protocol pass-through
    ss.search_app("shell:downloads")     # → shell folder
    ss.search_app("god mode")            # → Windows GUID shell
    ss.search_app("youtube")             # → https://youtube.com (web fallback)

    # Files
    ss.search_files("hey.txt")           # → list of matches
    ss.search_files("*.png")             # → all PNGs on disk
    ss.search_files(".env")              # → hidden dot-files

    # Folders
    ss.search_folders("downloads")       # → list of Download dirs
    ss.search_folders("node_modules")    # → all node_modules on disk
    ss.search_folders(".git")            # → all git repos found
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .app_searcher    import AppSearcher
from .file_searcher   import FileSearcher
from .folder_searcher import FolderSearcher

logger = logging.getLogger(__name__)


class SystemSearcher:
    """
    Single façade over AppSearcher, FileSearcher, FolderSearcher.
    Instantiate once and reuse — all three searchers cache internally.
    """

    def __init__(self):
        self._apps    = AppSearcher()
        self._files   = FileSearcher()
        self._folders = FolderSearcher()

    # ─────────────────────────────────────────────────────────────────────────
    #  search_app
    # ─────────────────────────────────────────────────────────────────────────
    def search_app(self, query: str, include_icon: bool = True) -> Optional[Dict[str, Any]]:
        """
        Find an application, system tool, or web service.

        Resolution order:
          1. ms-settings / shell: protocol pass-through
          2. Natural-language map  (Windows MMC, CPL, power tools …)
          3. Installed apps        (UWP, registry, Start Menu, PATH, FS scan)
          4. Web fallback          (KNOWN_WEBSITES dict → browser URL)

        Args:
            include_icon: If True (default), resolves and attaches icon data.
                          Set False for faster lookups when you don't need icons.

        Returns:
            dict with keys: name, path, type, launch_method, source,
                            icon_b64 (base64 PNG or None),
                            icon_url (favicon URL or None for websites)
            None if absolutely nothing found.
        """
        if not query or not query.strip():
            logger.warning("[SystemSearcher] search_app: empty query")
            return None

        result = self._apps.find_app(query.strip(), include_icon=include_icon)

        if result is None:
            logger.info("[SystemSearcher] search_app: no result for '%s'", query)
        else:
            logger.info("[SystemSearcher] search_app: '%s' → %s (%s)",
                        query, result.get("path"), result.get("type"))
        return result

    # ─────────────────────────────────────────────────────────────────────────
    #  search_files
    # ─────────────────────────────────────────────────────────────────────────
    def search_files(self, query: str,
                     search_paths: Optional[List[str]] = None,
                     deep: bool = True) -> List[Dict[str, Any]]:
        """
        Find files matching *query* anywhere on the system (including hidden).

        Args:
            query:        Filename (``hey.txt``), pattern (``*.png``),
                          extension (``.env``), or partial name.
            search_paths: Optional list of directory paths to restrict search.
            deep:         Scan full filesystem if True (default).  Set False
                          for quick priority-directory search only.

        Returns:
            List of file dicts, each with:
                name, path, size (bytes), modified (ISO), hidden, extension.
            Empty list if nothing found (never raises).
        """
        if not query or not query.strip():
            logger.warning("[SystemSearcher] search_files: empty query")
            return []

        results = self._files.search(query.strip(), search_paths, deep)

        if not results:
            logger.info("[SystemSearcher] search_files: no files found for '%s'", query)
        else:
            logger.info("[SystemSearcher] search_files: %d file(s) for '%s'",
                        len(results), query)
        return results

    # ─────────────────────────────────────────────────────────────────────────
    #  search_folders
    # ─────────────────────────────────────────────────────────────────────────
    def search_folders(self, query: str,
                       search_paths: Optional[List[str]] = None,
                       deep: bool = True) -> List[Dict[str, Any]]:
        """
        Find directories matching *query* anywhere on the system
        (including hidden dirs like ``.git``, ``AppData``, etc.).

        Args:
            query:        Folder name, glob, or partial name.
            search_paths: Optional restrict roots.
            deep:         Full filesystem scan if True (default).

        Returns:
            List of folder dicts, each with:
                name, path, modified (ISO), hidden, item_count.
            Empty list if nothing found.
        """
        if not query or not query.strip():
            logger.warning("[SystemSearcher] search_folders: empty query")
            return []

        results = self._folders.search(query.strip(), search_paths, deep)

        if not results:
            logger.info("[SystemSearcher] search_folders: no folders for '%s'", query)
        else:
            logger.info("[SystemSearcher] search_folders: %d dir(s) for '%s'",
                        len(results), query)
        return results

    # ─────────────────────────────────────────────────────────────────────────
    #  Convenience helpers
    # ─────────────────────────────────────────────────────────────────────────
    def add_website(self, name: str, url: str) -> None:
        """Register a custom website shortcut used by search_app fallback."""
        self._apps.add_website(name, url)

    def get_all_apps(self) -> List[Dict[str, str]]:
        """Return every cached app entry (useful for building a launcher UI)."""
        return self._apps.get_all_apps()


# ─────────────────────────────────────────────────────────────────────────────
#  Module-level singleton + bare functions (optional convenience)
# ─────────────────────────────────────────────────────────────────────────────
_instance: Optional[SystemSearcher] = None


def _get() -> SystemSearcher:
    global _instance
    if _instance is None:
        _instance = SystemSearcher()
    return _instance


def search_app(query: str) -> Optional[Dict[str, Any]]:
    """Module-level shortcut: search_app('chrome')"""
    return _get().search_app(query)


def search_files(query: str, **kwargs) -> List[Dict[str, Any]]:
    """Module-level shortcut: search_files('hey.txt')"""
    return _get().search_files(query, **kwargs)


def search_folders(query: str, **kwargs) -> List[Dict[str, Any]]:
    """Module-level shortcut: search_folders('downloads')"""
    return _get().search_folders(query, **kwargs)