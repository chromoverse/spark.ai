"""
Universal App Resolver - handles both system apps AND web apps/sites.
Smart fallback: if not a system app, treats it as a URL/website.
"""

import os
import sys
import logging
from typing import Optional, Dict, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# Popular websites/services with their URLs
# User can just say "open youtube" instead of full URL
KNOWN_WEBSITES = {
    # Social Media
    "youtube": "https://youtube.com",
    "twitter": "https://twitter.com",
    "x": "https://x.com",
    "facebook": "https://facebook.com",
    "instagram": "https://instagram.com",
    "linkedin": "https://linkedin.com",
    "reddit": "https://reddit.com",
    "tiktok": "https://tiktok.com",
    
    # Streaming
    "netflix": "https://netflix.com",
    "disney": "https://disneyplus.com",
    "hulu": "https://hulu.com",
    "prime": "https://primevideo.com",
    "spotify": "https://spotify.com",
    "twitch": "https://twitch.tv",
    
    # Productivity
    "github": "https://github.com",
    "gitlab": "https://gitlab.com",
    "notion": "https://notion.so",
    "figma": "https://figma.com",
    "gmail": "https://gmail.com",
    "outlook": "https://outlook.com",
    "drive": "https://drive.google.com",
    "docs": "https://docs.google.com",
    "sheets": "https://sheets.google.com",
    
    # Other
    "amazon": "https://amazon.com",
    "ebay": "https://ebay.com",
    "wikipedia": "https://wikipedia.org",
    "stackoverflow": "https://stackoverflow.com",
    "claude": "https://claude.ai",
    "chatgpt": "https://chat.openai.com",
    
    # Movies/Entertainment
    "netmirror": "https://net20.cc/home", 
    "cineby": "https://www.cineby.gd",
}


class AppResolver:
    """
    Universal resolver: finds system apps OR resolves to URLs.
    
    Resolution order:
    1. System-installed apps (via AppSearcher)
    2. Known website shortcuts (e.g., "youtube" → youtube.com)
    3. Direct URLs (e.g., "github.com/user/repo")
    4. Fallback: treat as search query for default browser
    """
    
    def __init__(self, app_searcher):
        """
        Args:
            app_searcher: Instance of AppSearcher for finding system apps
        """
        self.app_searcher = app_searcher
        self.logger = logging.getLogger("client.utils.AppResolver")
    
    def resolve(self, target: str) -> Tuple[str, str]:
        """
        Resolve a target to either a system app path or a URL.
        
        Args:
            target: User's request (e.g., "camera", "youtube", "github.com/user/repo")
            
        Returns:
            Tuple of (resolved_path_or_url, type)
            - type can be: "system_app", "url", "website"
        """
        self.logger.info(f"Resolving target: '{target}'")
        
        target_lower = target.lower().strip()
        
        # 1. FIRST: Try system-installed apps
        system_app = self.app_searcher.find_app(target)
        if system_app:
            self.logger.info(f"✅ Found system app: {system_app}")
            return (system_app, "system_app")
        
        # 2. Check if it's already a full URL
        if self._is_url(target):
            self.logger.info(f"✅ Detected URL: {target}")
            return (self._normalize_url(target), "url")
        
        # 3. Check known website shortcuts
        if target_lower in KNOWN_WEBSITES:
            url = KNOWN_WEBSITES[target_lower]
            self.logger.info(f"✅ Matched website shortcut: {target} → {url}")
            return (url, "website")
        
        # 4. Check if it looks like a domain (e.g., "github.com", "example.com")
        if self._looks_like_domain(target):
            url = self._normalize_url(target)
            self.logger.info(f"✅ Detected domain: {target} → {url}")
            return (url, "url")
        
        # 5. Fallback: Treat as website name and add .com
        # Example: "amazon" → "amazon.com"
        fallback_url = f"https://{target_lower}.com"
        self.logger.info(f"⚠️ Fallback to .com domain: {fallback_url}")
        return (fallback_url, "website")
    
    def _is_url(self, text: str) -> bool:
        """Check if text is a valid URL with protocol."""
        try:
            result = urlparse(text)
            return all([result.scheme, result.netloc])
        except:
            return False
    
    def _looks_like_domain(self, text: str) -> bool:
        """
        Check if text looks like a domain name.
        Examples: github.com, example.org, localhost:3000
        """
        # Has a dot and no spaces
        if '.' in text and ' ' not in text:
            # Check for common TLDs or looks like domain
            tlds = ['.com', '.org', '.net', '.io', '.ai', '.dev', '.app', '.co', 
                   '.tv', '.me', '.so', '.gg', '.xyz']
            if any(text.lower().endswith(tld) for tld in tlds):
                return True
            
            # Check for localhost or IP patterns
            if text.startswith('localhost') or text.count('.') >= 2:
                return True
        
        return False
    
    def _normalize_url(self, url: str) -> str:
        """
        Ensure URL has a protocol (add https:// if missing).
        """
        if not url.startswith(('http://', 'https://', 'file://', 'ftp://')):
            return f"https://{url}"
        return url
    
    def add_custom_website(self, name: str, url: str):
        """
        Allow users to add their own website shortcuts dynamically.
        
        Example:
            resolver.add_custom_website("movies", "https://github.com/cineby/netmirror")
        """
        KNOWN_WEBSITES[name.lower()] = url
        self.logger.info(f"Added custom website: {name} → {url}")
    
    def get_type_description(self, resolve_type: str) -> str:
        """Get human-readable description of resolve type."""
        descriptions = {
            "system_app": "System application",
            "url": "Website URL",
            "website": "Known website shortcut"
        }
        return descriptions.get(resolve_type, "Unknown")


# Example usage:
if __name__ == "__main__":
    from .app_searcher import AppSearcher
    
    searcher = AppSearcher()
    resolver = AppResolver(searcher)
    
    # Test cases
    test_targets = [
        "camera",           # System app
        "chrome",           # System app
        "youtube",          # Known website
        "github.com",       # Domain
        "https://example.com",  # Full URL
        "netflix",          # Known website
        "stackoverflow",    # Known website
        "randomapp",        # Fallback to .com
    ]
    
    print("\n=== AppResolver Test ===\n")
    for target in test_targets:
        path, type_ = resolver.resolve(target)
        print(f"'{target}' → {type_}: {path}")