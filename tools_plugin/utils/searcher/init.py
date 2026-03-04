"""
searcher — Cross-platform deep system search package.

Quick start
───────────
    from searcher import SystemSearcher

    ss = SystemSearcher()
    ss.search_app("event viewer")
    ss.search_files("hey.txt")
    ss.search_folders("downloads")

Or use module-level functions:
    from searcher import search_app, search_files, search_folders
"""

from .system_searcher import (
    SystemSearcher,
    search_app,
    search_files,
    search_folders,
)
from .app_searcher    import AppSearcher, KNOWN_WEBSITES, NATURAL_LANGUAGE_MAP, PROTOCOL_HANDLERS
from .file_searcher   import FileSearcher
from .folder_searcher import FolderSearcher
from .icon_resolver   import IconResolver

__all__ = [
    "SystemSearcher",
    "search_app",
    "search_files",
    "search_folders",
    "AppSearcher",
    "FileSearcher",
    "FolderSearcher",
    "IconResolver",
    "KNOWN_WEBSITES",
    "NATURAL_LANGUAGE_MAP",
    "PROTOCOL_HANDLERS",
]