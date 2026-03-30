"""
Path Resolver Utility for LLM-Generated Paths

This module resolves paths that may be:
- Relative paths (e.g., "Desktop/file.pdf")
- Common folder names (e.g., "desktop", "documents")
- Home directory shortcuts (e.g., "~/file.pdf")
- Absolute paths (passed through with normalization)

The goal is to make tools "path-aware" so LLMs can use natural language paths.
"""

import os
import platform
from pathlib import Path
from typing import Tuple, Optional
import re


class PathResolver:
    """
    Resolves LLM-generated paths to absolute system paths.
    
    Features:
    - Expands ~ to user home directory
    - Resolves common folder names (Desktop, Documents, Downloads, etc.)
    - Handles relative paths from user home
    - Normalizes path separators for the current OS
    - Validates paths exist (optional)
    
    Usage:
        resolver = PathResolver()
        
        # All of these resolve correctly:
        resolver.resolve("desktop")           # → C:/Users/You/Desktop
        resolver.resolve("Desktop/report.pdf") # → C:/Users/You/Desktop/report.pdf
        resolver.resolve("~/Documents")        # → C:/Users/You/Documents
        resolver.resolve("downloads/file.zip") # → C:/Users/You/Downloads/file.zip
    """
    
    # Common folder aliases (lowercase for case-insensitive matching)
    FOLDER_ALIASES = {
        # English
        "desktop": "Desktop",
        "documents": "Documents",
        "downloads": "Downloads",
        "pictures": "Pictures",
        "photos": "Pictures",
        "images": "Pictures",
        "music": "Music",
        "audio": "Music",
        "videos": "Videos",
        "movies": "Videos",
        "home": "",
        "user": "",
        
        # Common abbreviations
        "docs": "Documents",
        "pics": "Pictures",
        "vids": "Videos",
        
        # Windows specific
        "appdata": "AppData/Local",
        "local": "AppData/Local",
        "roaming": "AppData/Roaming",
        
        # macOS specific  
        "applications": "Applications",
        "apps": "Applications",
        
        # Linux specific
        "config": ".config",
        "share": ".local/share",
    }
    
    def __init__(self):
        self.system = platform.system()
        self.home = Path.home()
        self._setup_system_folders()
    
    def _setup_system_folders(self):
        """Setup OS-specific folder paths."""
        if self.system == "Windows":
            # Windows: Use known folders
            self.known_folders = {
                "Desktop": self.home / "Desktop",
                "Documents": self.home / "Documents",
                "Downloads": self.home / "Downloads",
                "Pictures": self.home / "Pictures",
                "Music": self.home / "Music",
                "Videos": self.home / "Videos",
            }
        elif self.system == "Darwin":
            # macOS
            self.known_folders = {
                "Desktop": self.home / "Desktop",
                "Documents": self.home / "Documents",
                "Downloads": self.home / "Downloads",
                "Pictures": self.home / "Pictures",
                "Music": self.home / "Music",
                "Videos": self.home / "Movies",
                "Applications": Path("/Applications"),
            }
        else:
            # Linux
            self.known_folders = {
                "Desktop": self.home / "Desktop",
                "Documents": self.home / "Documents",
                "Downloads": self.home / "Downloads",
                "Pictures": self.home / "Pictures",
                "Music": self.home / "Music",
                "Videos": self.home / "Videos",
            }
    
    def resolve(self, path: str, must_exist: bool = False) -> Tuple[str, bool, Optional[str]]:
        """
        Resolve a path to its absolute form.
        
        Args:
            path: The path to resolve (can be relative, alias, or absolute)
            must_exist: If True, returns error if path doesn't exist
            
        Returns:
            Tuple of (resolved_path, success, error_message)
            - resolved_path: The absolute path (or original if failed)
            - success: True if resolution succeeded
            - error_message: None if success, error description otherwise
        """
        if not path or not isinstance(path, str):
            return "", False, "Path is empty or invalid"
        
        # Normalize path separators
        path = path.replace("\\", "/").strip()
        
        # Remove quotes if present (LLMs sometimes add them)
        path = path.strip('"\'')
        
        try:
            resolved = self._resolve_internal(path)
            
            # Validate existence if required
            if must_exist and not os.path.exists(resolved):
                return resolved, False, f"Path does not exist: {resolved}"
            
            return resolved, True, None
            
        except Exception as e:
            return path, False, f"Path resolution failed: {str(e)}"
    
    def _resolve_internal(self, path: str) -> str:
        """Internal resolution logic."""
        
        # 1. Handle home directory shortcut
        if path.startswith("~"):
            return str(self._expand_home(path))
        
        # 2. Handle absolute paths (just normalize)
        if os.path.isabs(path):
            return os.path.normpath(path)
        
        # 3. Check if first segment is a known folder alias
        parts = path.split("/", 1)
        first_part = parts[0].lower()
        
        if first_part in self.FOLDER_ALIASES:
            target_folder = self.FOLDER_ALIASES[first_part]
            
            if target_folder == "":  # "home" or "user"
                base = self.home
            elif "/" in target_folder:  # Nested path like "AppData/Local"
                base = self.home / target_folder
            else:
                # Use known folder if available, otherwise construct from home
                base = self.known_folders.get(target_folder, self.home / target_folder)
            
            if len(parts) > 1:
                return str(base / parts[1])
            else:
                return str(base)
        
        # 4. Check if first segment matches a known folder (case-insensitive)
        for folder_name, folder_path in self.known_folders.items():
            if first_part.lower() == folder_name.lower():
                if len(parts) > 1:
                    return str(folder_path / parts[1])
                else:
                    return str(folder_path)
        
        # 5. Treat as relative to home directory
        return str(self.home / path)
    
    def _expand_home(self, path: str) -> Path:
        """Expand ~ to home directory."""
        if path == "~":
            return self.home
        elif path.startswith("~/"):
            return self.home / path[2:]
        else:
            # ~username format (rarely used by LLMs but handle it)
            return Path(os.path.expanduser(path))
    
    def resolve_file(self, path: str, must_exist: bool = True) -> Tuple[str, bool, Optional[str]]:
        """
        Resolve a file path with file-specific validation.
        
        Args:
            path: The file path to resolve
            must_exist: If True, validates that file exists (not just directory)
            
        Returns:
            Tuple of (resolved_path, success, error_message)
        """
        resolved, success, error = self.resolve(path, must_exist=False)
        
        if not success:
            return resolved, success, error
        
        if must_exist:
            if not os.path.exists(resolved):
                return resolved, False, f"File does not exist: {resolved}"
            if not os.path.isfile(resolved):
                return resolved, False, f"Path is not a file: {resolved}"
        
        return resolved, True, None
    
    def resolve_folder(self, path: str, must_exist: bool = True, create: bool = False) -> Tuple[str, bool, Optional[str]]:
        """
        Resolve a folder path with folder-specific validation.
        
        Args:
            path: The folder path to resolve
            must_exist: If True, validates that folder exists
            create: If True, creates the folder if it doesn't exist
            
        Returns:
            Tuple of (resolved_path, success, error_message)
        """
        resolved, success, error = self.resolve(path, must_exist=False)
        
        if not success:
            return resolved, success, error
        
        if not os.path.exists(resolved):
            if create:
                try:
                    os.makedirs(resolved, exist_ok=True)
                    return resolved, True, None
                except Exception as e:
                    return resolved, False, f"Failed to create folder: {str(e)}"
            elif must_exist:
                return resolved, False, f"Folder does not exist: {resolved}"
        
        if must_exist and not os.path.isdir(resolved):
            return resolved, False, f"Path is not a folder: {resolved}"
        
        return resolved, True, None
    
    def get_common_folders(self) -> dict:
        """
        Get a dictionary of common folders for LLM context.
        
        Returns:
            Dict mapping folder names to their absolute paths
        """
        result = {}
        for name, path in self.known_folders.items():
            result[name.lower()] = str(path)
        return result
    
    def get_path_hints(self) -> str:
        """
        Get a human-readable string of path hints for LLM context.
        
        Returns:
            String with common folder paths the LLM can use
        """
        hints = ["Common folder paths you can use:"]
        for name, path in self.known_folders.items():
            hints.append(f"  - {name}: {path}")
        hints.append("  - Use ~ or 'home' for your home directory")
        hints.append("  - Relative paths are resolved from your home directory")
        return "\n".join(hints)


# Singleton instance
_path_resolver: Optional[PathResolver] = None


def get_path_resolver() -> PathResolver:
    """Get the global PathResolver instance."""
    global _path_resolver
    if _path_resolver is None:
        _path_resolver = PathResolver()
    return _path_resolver


def resolve_path(path: str, must_exist: bool = False) -> Tuple[str, bool, Optional[str]]:
    """
    Convenience function to resolve a path using the global resolver.
    
    Args:
        path: The path to resolve
        must_exist: If True, returns error if path doesn't exist
        
    Returns:
        Tuple of (resolved_path, success, error_message)
    """
    return get_path_resolver().resolve(path, must_exist)


def resolve_file_path(path: str, must_exist: bool = True) -> Tuple[str, bool, Optional[str]]:
    """
    Convenience function to resolve a file path.
    
    Args:
        path: The file path to resolve
        must_exist: If True, validates that file exists
        
    Returns:
        Tuple of (resolved_path, success, error_message)
    """
    return get_path_resolver().resolve_file(path, must_exist)


def resolve_folder_path(path: str, must_exist: bool = True, create: bool = False) -> Tuple[str, bool, Optional[str]]:
    """
    Convenience function to resolve a folder path.
    
    Args:
        path: The folder path to resolve
        must_exist: If True, validates that folder exists
        create: If True, creates the folder if it doesn't exist
        
    Returns:
        Tuple of (resolved_path, success, error_message)
    """
    return get_path_resolver().resolve_folder(path, must_exist, create)


# ── USAGE EXAMPLE ─────────────────────────────────────────────────
if __name__ == "__main__":
    resolver = PathResolver()
    
    test_paths = [
        "desktop",
        "Desktop/report.pdf",
        "~/Documents",
        "downloads/file.zip",
        "pics/vacation.jpg",
        "C:/Users/test/file.txt",  # Absolute path
        "home/projects/code",
    ]
    
    print("Path Resolver Test\n" + "="*50)
    for p in test_paths:
        resolved, success, error = resolver.resolve(p)
        status = "✅" if success else "❌"
        print(f"{status} '{p}' → {resolved}")
        if error:
            print(f"   Error: {error}")
    
    print("\n" + resolver.get_path_hints())
