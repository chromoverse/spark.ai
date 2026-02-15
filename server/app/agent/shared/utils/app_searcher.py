"""
Dynamic cross-platform system search utility - Raycast style.
Automatically discovers ALL launchable apps without hardcoding.
"""

import os
import sys
import shutil
import subprocess
import logging
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

logger = logging.getLogger(__name__)


# CRITICAL: Known protocol handlers that must take precedence
# These are NOT found by file scanning but are valid Windows launch methods
PROTOCOL_HANDLERS = {
    "camera": "microsoft.windows.camera:",
    "calculator": "calculator:",
    "settings": "ms-settings:",
}


class AppSearcher:
    """
    Dynamic system-wide application searcher.
    No hardcoded apps - discovers everything automatically.
    """
    
    def __init__(self):
        self.os_type = sys.platform
        self.logger = logging.getLogger("client.utils.SystemSearcher")
        self._app_cache = {}  # Cache for performance
        self._cache_timestamp = 0
        self._cache_ttl = 300  # 5 minutes
        
    def find_app(self, query: str) -> Optional[str]:
        """
        Dynamically search for ANY application on the system.
        
        Args:
            query: Search query (e.g., "task", "whats", "chrome")
            
        Returns:
            Path to the best matching application or None.
        """
        self.logger.info(f"Searching for: '{query}' on {self.os_type}")
        
        # 1. FIRST: Check protocol handlers (Windows UWP apps)
        if self.os_type == "win32":
            query_lower = query.lower()
            if query_lower in PROTOCOL_HANDLERS:
                protocol = PROTOCOL_HANDLERS[query_lower]
                self.logger.info(f"Using protocol handler: {protocol}")
                return protocol
        
        # 2. Refresh cache if expired
        if time.time() - self._cache_timestamp > self._cache_ttl:
            self._refresh_cache()
        
        # 3. Search in cache
        matches = self._fuzzy_search_apps(query)
        
        if matches:
            # Return best match (highest score)
            best_match = max(matches, key=lambda x: x[1])
            self.logger.info(f"Best match: {best_match[0]} (score: {best_match[1]})")
            return best_match[0]
        
        return None
    
    def _refresh_cache(self):
        """Scan system and build app cache."""
        self.logger.info("Refreshing app cache...")
        self._app_cache.clear()
        
        if self.os_type == "win32":
            self._scan_windows()
        elif self.os_type == "darwin":
            self._scan_macos()
        elif self.os_type.startswith("linux"):
            self._scan_linux()
        
        self._cache_timestamp = time.time()
        self.logger.info(f"Cache refreshed: {len(self._app_cache)} apps found")
    
    def _scan_windows(self):
        """Scan Windows system for ALL launchable apps."""
        # First, scan Windows Store apps (UWP/MSIX) - WHERE WHATSAPP LIVES!
        self._scan_windows_store_apps()
        
        sources = [
            # Start Menu shortcuts
            (os.path.join(os.environ.get("PROGRAMDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs"), [".lnk"]),
            (os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "Microsoft", "Windows", "Start Menu", "Programs"), [".lnk"]),
            
            # Program Files executables
            (os.environ.get("PROGRAMFILES", "C:\\Program Files"), [".exe"]),
            (os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)"), [".exe"]),
            
            # System32 - BUT EXCLUDE KNOWN SETTINGS/UI HOSTS
            (os.path.join(os.environ.get("SYSTEMROOT", "C:\\Windows"), "System32"), [".exe"]),
            
            # User local apps
            (os.path.join(os.path.expanduser("~"), "AppData", "Local", "Programs"), [".exe", ".lnk"]),
        ]
        
        # Parallel scanning for speed
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = []
            for base_path, extensions in sources:
                if os.path.exists(base_path):
                    futures.append(executor.submit(self._scan_directory, base_path, extensions, max_depth=3))
            
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    self.logger.error(f"Scan error: {e}")
    
    def _scan_windows_store_apps(self):
        """
        Scan Windows Store (UWP/MSIX) apps - THIS IS WHERE WHATSAPP IS!
        Uses PowerShell to query installed packages.
        """
        try:
            # PowerShell command to get all installed apps
            ps_command = """
            Get-AppxPackage | ForEach-Object {
                $_.Name + '|' + $_.PackageFamilyName
            }
            """
            
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_command],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if '|' not in line:
                        continue
                    
                    name, family_name = line.strip().split('|', 1)
                    
                    # Clean up the name (remove company prefix)
                    clean_name = name.split('.')[-1]  # e.g., "5319275A.WhatsAppDesktop" -> "WhatsAppDesktop"
                    
                    # Store using shell:AppsFolder protocol (Windows way to launch Store apps)
                    app_id = f"shell:AppsFolder\\{family_name}!App"
                    
                    key = clean_name.lower()
                    if key not in self._app_cache:
                        self._app_cache[key] = {
                            'path': app_id,
                            'name': clean_name,
                            'type': 'uwp'
                        }
                        
        except Exception as e:
            self.logger.error(f"Failed to scan Windows Store apps: {e}")
    
    def _scan_macos(self):
        """Scan macOS system for ALL .app bundles."""
        # Use mdfind (Spotlight) - fastest way
        try:
            cmd = ["mdfind", "kMDItemContentTypeTree=com.apple.application-bundle"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if line and line.endswith('.app'):
                        app_name = os.path.basename(line).replace('.app', '')
                        self._app_cache[app_name.lower()] = {
                            'path': line,
                            'name': app_name,
                            'type': 'app'
                        }
        except Exception as e:
            self.logger.error(f"mdfind failed: {e}")
            
            # Fallback: manual scan
            search_paths = [
                "/Applications",
                "/System/Applications",
                os.path.expanduser("~/Applications"),
                "/System/Library/CoreServices"
            ]
            
            for path in search_paths:
                if os.path.exists(path):
                    self._scan_directory(path, [".app"], max_depth=2)
    
    def _scan_linux(self):
        """Scan Linux system for .desktop files and executables."""
        sources = [
            # .desktop files (primary source)
            ("/usr/share/applications", [".desktop"]),
            ("/usr/local/share/applications", [".desktop"]),
            (os.path.expanduser("~/.local/share/applications"), [".desktop"]),
            
            # Flatpak
            ("/var/lib/flatpak/exports/share/applications", [".desktop"]),
            (os.path.expanduser("~/.local/share/flatpak/exports/share/applications"), [".desktop"]),
            
            # Snap
            ("/var/lib/snapd/desktop/applications", [".desktop"]),
            
            # Binaries in PATH
            ("/usr/bin", [""]),
            ("/usr/local/bin", [""]),
        ]
        
        for base_path, extensions in sources:
            if os.path.exists(base_path):
                self._scan_directory(base_path, extensions, max_depth=1)
    
    def _scan_directory(self, path: str, extensions: List[str], max_depth: int = 2):
        """
        Recursively scan directory for launchable files.
        
        Args:
            path: Base directory to scan
            extensions: List of file extensions to look for (e.g., [".exe", ".lnk"])
            max_depth: Maximum recursion depth
        """
        # Blacklist: Executables that are NOT actual apps (just settings/helpers)
        BLACKLIST = [
            "camerasettingsuihost.exe",  # Camera settings UI, not the camera app
            "systemsettings.exe",        # Settings UI host
            "applicationframehost.exe",  # UWP container
        ]
        
        try:
            for root, dirs, files in os.walk(path):
                # Depth limiting
                depth = root[len(path):].count(os.sep)
                if depth > max_depth:
                    dirs[:] = []  # Don't recurse deeper
                    continue
                
                for file in files:
                    # Check extension
                    if extensions and not any(file.lower().endswith(ext) for ext in extensions):
                        continue
                    
                    # Skip if no extension filter and not executable
                    if not extensions and not os.access(os.path.join(root, file), os.X_OK):
                        continue
                    
                    # Skip blacklisted files
                    if file.lower() in BLACKLIST:
                        continue
                    
                    # Extract clean name
                    clean_name = file
                    for ext in [".exe", ".lnk", ".app", ".desktop"]:
                        clean_name = clean_name.replace(ext, "")
                    
                    full_path = os.path.join(root, file)
                    
                    # Store in cache
                    key = clean_name.lower()
                    if key not in self._app_cache:
                        self._app_cache[key] = {
                            'path': full_path,
                            'name': clean_name,
                            'type': 'app'
                        }
                        
        except PermissionError:
            pass  # Skip directories we can't access
        except Exception as e:
            self.logger.error(f"Error scanning {path}: {e}")
    
    def _fuzzy_search_apps(self, query: str) -> List[Tuple[str, float]]:
        """
        Fuzzy search through cached apps.
        
        Returns:
            List of (path, score) tuples, sorted by relevance.
        """
        query_lower = query.lower()
        matches = []
        
        for key, app_info in self._app_cache.items():
            score = self._calculate_match_score(query_lower, key, app_info['name'])
            if score > 0:
                matches.append((app_info['path'], score))
        
        return matches
    
    def _calculate_match_score(self, query: str, key: str, name: str) -> float:
        """
        Calculate relevance score for a search match.
        Higher score = better match.
        """
        score = 0.0
        
        # 1. Exact match (highest priority)
        if query == key:
            return 100.0
        
        # 2. Starts with query
        if key.startswith(query):
            score = 90.0
        
        # 3. Contains query as substring
        elif query in key:
            score = 70.0
        
        # 4. Fuzzy match (all chars in order)
        elif self._fuzzy_match(query, key):
            score = 50.0
        
        # 5. Word boundary match (e.g., "task" matches "Task Manager")
        elif any(word.startswith(query) for word in key.split()):
            score = 60.0
        
        # Boost for shorter names (more likely to be what user wants)
        if score > 0:
            length_penalty = len(key) / 100
            score -= length_penalty
        
        return score
    
    def _fuzzy_match(self, query: str, text: str) -> bool:
        """
        Check if all characters in query appear in text in order.
        Example: 'tskm' matches 'task manager'
        """
        q_idx = 0
        for char in text:
            if q_idx < len(query) and char == query[q_idx]:
                q_idx += 1
        return q_idx == len(query)
    
    def get_all_apps(self) -> List[Dict[str, str]]:
        """Get list of all discovered apps (for debugging/UI)."""
        if time.time() - self._cache_timestamp > self._cache_ttl:
            self._refresh_cache()
        
        return [
            {'name': info['name'], 'path': info['path']} 
            for info in self._app_cache.values()
        ]