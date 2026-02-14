"""
API Key Manager — Utility for persisting LLM provider API keys.

Saves keys to Windows system environment variables (User-level)
so they survive reboots without needing a .env file.

Features:
    - Supports single key or array of keys per provider
    - Auto key rotation: when one key is exhausted, automatically uses the next
    - One-shot bulk load: reads ALL provider keys from the Windows registry
      in a single handle open, then serves from memory forever.
    - Auto-syncs into os.environ so BaseClient._load_keys() finds keys
      via os.getenv() without any extra I/O.

Usage:
    from app.ai.providers.key_manager import register_api_key, list_registered_keys, get_next_key

    # Add a single key
    register_api_key("groq", "gsk_abc123...")

    # Add multiple keys (array) - they will be used sequentially
    register_api_key("groq", ["gsk_key1...", "gsk_key2...", "gsk_key3..."])

    # Add by env var name directly
    register_api_key("GEMINI_API_KEY", "AIzaSy...")

    # Get the next available key (rotates through array)
    key = get_next_key("groq")

    # List all registered keys (instant — served from cache)
    list_registered_keys()
"""
import os
import sys
import json
import logging
from typing import Optional, Dict, List, Union, Any

logger = logging.getLogger(__name__)

# ── Provider name → env var mapping ──
PROVIDER_ENV_MAP: Dict[str, str] = {
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


# ═══════════════════════════════════════════════════════════════
#  In-memory key cache — loads from registry ONCE, then instant
#  Supports arrays of keys with rotation
# ═══════════════════════════════════════════════════════════════

class _KeyCache:
    """
    Module-level cache for API keys.

    On first access, bulk-reads every PROVIDER_ENV_MAP key from the
    Windows User registry in a single handle open/close and populates
    os.environ.  All subsequent reads are pure dict lookups — zero I/O.
    
    Supports both single keys and arrays of keys. When multiple keys
    are stored, they are rotated sequentially.
    """

    _loaded: bool = False
    # Cache stores lists of keys: {env_name: ["key1", "key2", ...]}
    _cache: Dict[str, List[str]] = {}
    # Track current key index for rotation: {env_name: current_index}
    _rotation_index: Dict[str, int] = {}

    # ── public API ──

    @classmethod
    def get_all(cls) -> Dict[str, List[str]]:
        """Return the full {env_name: [keys]} dict (loads on first call)."""
        if not cls._loaded:
            cls._bulk_load()
        return cls._cache

    @classmethod
    def get(cls, env_name: str) -> List[str]:
        """Get the list of keys from cache for a given env_name."""
        if not cls._loaded:
            cls._bulk_load()
        return cls._cache.get(env_name, [])

    @classmethod
    def get_first(cls, env_name: str) -> Optional[str]:
        """Get the first/primary key from cache (for backward compatibility)."""
        keys = cls.get(env_name)
        return keys[0] if keys else None

    @classmethod
    def set(cls, env_name: str, value: Union[str, List[str]]) -> None:
        """
        Update cache + os.environ after a registry write.
        
        Args:
            env_name: The environment variable name
            value: Either a single key string or a list of keys
        """
        if not cls._loaded:
            cls._bulk_load()
        
        # Normalize to list
        if isinstance(value, str):
            keys = [value.strip()] if value.strip() else []
        else:
            keys = [k.strip() for k in value if k.strip()]
        
        cls._cache[env_name] = keys
        
        # Store first key in os.environ for backward compatibility
        if keys:
            os.environ[env_name] = keys[0]
        else:
            os.environ.pop(env_name, None)
        
        # Reset rotation index when keys are updated
        cls._rotation_index[env_name] = 0

    @classmethod
    def delete(cls, env_name: str) -> None:
        """Remove from cache + os.environ after a registry delete."""
        if not cls._loaded:
            cls._bulk_load()
        cls._cache[env_name] = []
        cls._rotation_index[env_name] = 0
        os.environ.pop(env_name, None)

    @classmethod
    def get_next_key(cls, env_name: str) -> Optional[str]:
        """
        Get the next key in rotation.
        
        Returns the current key and advances the rotation index.
        When the last key is exhausted, wraps around to the first key.
        
        Args:
            env_name: The environment variable name
            
        Returns:
            The next key in rotation, or None if no keys are available
        """
        if not cls._loaded:
            cls._bulk_load()
        
        keys = cls._cache.get(env_name, [])
        if not keys:
            return None
        
        # Get current index, default to 0
        current_index = cls._rotation_index.get(env_name, 0)
        
        # Get the key at current index
        key = keys[current_index]
        
        # Advance index for next call (wrap around if at end)
        next_index = (current_index + 1) % len(keys)
        cls._rotation_index[env_name] = next_index
        
        return key

    @classmethod
    def rotate_to_next(cls, env_name: str) -> Optional[str]:
        """
        Force rotate to the next key (call this when a key is exhausted).
        
        Args:
            env_name: The environment variable name
            
        Returns:
            The next key in rotation, or None if no keys are available
        """
        if not cls._loaded:
            cls._bulk_load()
        
        keys = cls._cache.get(env_name, [])
        if not keys:
            return None
        
        # Advance index to next key
        current_index = cls._rotation_index.get(env_name, 0)
        next_index = (current_index + 1) % len(keys)
        cls._rotation_index[env_name] = next_index
        
        return keys[next_index]

    @classmethod
    def get_current_index(cls, env_name: str) -> int:
        """Get the current rotation index for a provider."""
        return cls._rotation_index.get(env_name, 0)

    @classmethod
    def get_key_count(cls, env_name: str) -> int:
        """Get the number of keys stored for a provider."""
        if not cls._loaded:
            cls._bulk_load()
        return len(cls._cache.get(env_name, []))

    # ── internals ──

    @classmethod
    def _bulk_load(cls) -> None:
        """
        Read ALL provider keys from the Windows User registry in one pass.

        Opens the HKCU\\Environment key once, reads every env var in
        PROVIDER_ENV_MAP, then closes it.  Also syncs found values into
        os.environ so that os.getenv() works everywhere else.
        
        Supports both:
        - JSON arrays: ["key1", "key2", ...]
        - Single key strings (backward compatibility)
        """
        env_names = list(PROVIDER_ENV_MAP.values())

        if sys.platform == "win32":
            import winreg

            try:
                reg_key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Environment",
                    0,
                    winreg.KEY_QUERY_VALUE,
                )
                try:
                    for env_name in env_names:
                        try:
                            value, _ = winreg.QueryValueEx(reg_key, env_name)
                            raw = str(value).strip() if value else None
                        except FileNotFoundError:
                            raw = None

                        # Parse the value - could be JSON array or single key
                        keys = cls._parse_keys(raw)
                        cls._cache[env_name] = keys
                        cls._rotation_index[env_name] = 0

                        # Sync first key into os.environ for backward compatibility
                        if keys:
                            os.environ[env_name] = keys[0]
                finally:
                    winreg.CloseKey(reg_key)
            except OSError as e:
                logger.warning(f"⚠️  Could not open registry Environment key: {e}")
                # Fallback: read from os.environ directly
                for env_name in env_names:
                    raw = os.getenv(env_name)
                    keys = cls._parse_keys(raw)
                    cls._cache[env_name] = keys
                    cls._rotation_index[env_name] = 0
                    if keys:
                        os.environ[env_name] = keys[0]
        else:
            # Non-Windows: just read os.environ
            for env_name in env_names:
                raw = os.getenv(env_name)
                keys = cls._parse_keys(raw)
                cls._cache[env_name] = keys
                cls._rotation_index[env_name] = 0
                if keys:
                    os.environ[env_name] = keys[0]

        cls._loaded = True
        loaded_count = sum(1 for v in cls._cache.values() if v)
        logger.info(
            f"🔑 KeyCache: bulk-loaded {loaded_count}/{len(env_names)} keys "
            f"from {'registry' if sys.platform == 'win32' else 'environ'}"
        )

    @classmethod
    def _parse_keys(cls, raw: Optional[str]) -> List[str]:
        """
        Parse raw value from registry into a list of keys.
        
        Handles:
        - JSON arrays: ["key1", "key2"]
        - Single key string: "key1"
        - None or empty
        """
        if not raw:
            return []
        
        raw = raw.strip()
        
        # Try parsing as JSON array
        if raw.startswith("["):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return [k.strip() for k in parsed if k.strip()]
            except (json.JSONDecodeError, ValueError):
                pass
        
        # Treat as single key
        return [raw]


def _resolve_env_key(provider_or_env: str) -> str:
    """
    Resolve a provider name or env var name to the actual env var name.

    Accepts:
        'groq'              → GROQ_API_KEY
        'gemini'            → GEMINI_API_KEY
        'openrouter'        → OPENROUTER_API_KEY
        'GROQ_API_KEY'      → GROQ_API_KEY  (passthrough)
    """
    lower = provider_or_env.strip().lower()
    if lower in PROVIDER_ENV_MAP:
        return PROVIDER_ENV_MAP[lower]

    # If it looks like an env var name already (uppercase with underscores)
    upper = provider_or_env.strip().upper()
    if upper.endswith("_API_KEY"):
        return upper

    raise ValueError(
        f"Unknown provider: '{provider_or_env}'. "
        f"Use one of: {list(PROVIDER_ENV_MAP.keys())} or a direct env var name like 'GROQ_API_KEY'"
    )


def _set_windows_env(name: str, value: str) -> None:
    """Persist an env var at the Windows User level (survives reboots)."""
    if sys.platform != "win32":
        raise RuntimeError("System env persistence is only supported on Windows")

    import winreg

    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Environment",
        0,
        winreg.KEY_SET_VALUE,
    )
    try:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    finally:
        winreg.CloseKey(key)

    # Broadcast WM_SETTINGCHANGE so other processes pick it up
    try:
        import ctypes
        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        SMTO_ABORTIFHUNG = 0x0002
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_SETTINGCHANGE, 0,
            "Environment", SMTO_ABORTIFHUNG, 5000, None,
        )
    except Exception:
        pass  # non-critical


def _delete_windows_env(name: str) -> None:
    """Remove an env var from the Windows User registry."""
    if sys.platform != "win32":
        raise RuntimeError("System env persistence is only supported on Windows")

    import winreg

    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Environment",
            0,
            winreg.KEY_SET_VALUE,
        )
        try:
            winreg.DeleteValue(key, name)
        finally:
            winreg.CloseKey(key)
    except FileNotFoundError:
        pass  # already doesn't exist


def register_api_key(provider_or_env: str, api_key: Union[str, List[str]]) -> str:
    """
    Save API key(s) to the system environment (persistent).

    Args:
        provider_or_env: Provider name ('groq', 'gemini', 'openrouter')
                         or env var name ('GROQ_API_KEY')
        api_key: The actual API key string OR a list of API keys.
                 When a list is provided, keys will be used sequentially
                 (rotated) when the previous key is exhausted.

    Returns:
        The env var name that was set

    Example:
        # Single key
        register_api_key("groq", "gsk_abc123...")
        
        # Multiple keys (array) - will be used sequentially
        register_api_key("groq", ["gsk_key1...", "gsk_key2...", "gsk_key3..."])
        
        # By env var name
        register_api_key("GEMINI_API_KEY", "AIzaSy...")
    """
    env_name = _resolve_env_key(provider_or_env)
    
    # Normalize to list
    if isinstance(api_key, str):
        keys = [api_key.strip()] if api_key.strip() else []
    else:
        keys = [k.strip() for k in api_key if k.strip()]
    
    if not keys:
        raise ValueError("API key cannot be empty")
    
    # Store as JSON array in registry
    if len(keys) == 1:
        # For single key, store as plain string for backward compatibility
        stored_value = keys[0]
    else:
        # For multiple keys, store as JSON array
        stored_value = json.dumps(keys)
    
    print(f"Saving {env_name} to system environment...")
    _set_windows_env(env_name, stored_value)

    # Update cache + os.environ immediately (no stale reads)
    _KeyCache.set(env_name, keys)
    
    if len(keys) == 1:
        logger.info(f"✅ Saved {env_name} to system environment ({keys[0][:8]}...)")
    else:
        logger.info(f"✅ Saved {env_name} to system environment with {len(keys)} keys")
    return env_name


def remove_api_key(provider_or_env: str) -> str:
    """
    Remove an API key from the system environment.

    Args:
        provider_or_env: Provider name or env var name

    Returns:
        The env var name that was removed
    """
    env_name = _resolve_env_key(provider_or_env)

    _delete_windows_env(env_name)

    # Update cache + os.environ immediately
    _KeyCache.delete(env_name)

    logger.info(f"🗑️  Removed {env_name} from system environment")
    return env_name


def list_registered_keys() -> Dict[str, Any]:
    """
    List all provider API keys (instant — served from cache).

    Returns:
        Dict mapping env var name → dict with keys and masked value
        
    Example:
        {
            'GROQ_API_KEY': {
                'keys': ['gsk_HmMn...', 'gsk_AbCd...'],
                'masked': 'gsk_HmMn****CP5',
                'count': 2,
                'current_index': 0
            },
            'GEMINI_API_KEY': None,
        }
    """
    result: Dict[str, Any] = {}
    cached = _KeyCache.get_all()

    for env_name in PROVIDER_ENV_MAP.values():
        keys = cached.get(env_name, [])
        if keys:
            # Mask the first key for display: show first 8 + last 3 chars
            first_key = keys[0]
            if len(first_key) > 15:
                masked = f"{first_key[:8]}****{first_key[-3:]}"
            else:
                masked = f"{first_key[:4]}****"
            
            result[env_name] = {
                'keys': keys,
                'masked': masked,
                'count': len(keys),
                'current_index': _KeyCache.get_current_index(env_name)
            }
        else:
            result[env_name] = None

    return result


def list_keys_simple() -> Dict[str, Optional[str]]:
    """
    Simple list of registered keys (backward compatible format).
    
    Returns only the masked first key for each provider.
    """
    result: Dict[str, Optional[str]] = {}
    cached = _KeyCache.get_all()

    for env_name in PROVIDER_ENV_MAP.values():
        keys = cached.get(env_name, [])
        if keys:
            first_key = keys[0]
            if len(first_key) > 15:
                masked = f"{first_key[:8]}****{first_key[-3:]}"
            else:
                masked = f"{first_key[:4]}****"
            result[env_name] = masked
        else:
            result[env_name] = None

    return result


def get_raw_key(provider_or_env: str) -> Optional[str]:
    """
    Get the raw (unmasked) first API key for a provider from cache.
    
    For backward compatibility. Returns the first key in the list.
    Use get_all_keys() to get all keys or get_next_key() for rotation.
    """
    env_name = _resolve_env_key(provider_or_env)
    return _KeyCache.get_first(env_name)


def get_all_keys(provider_or_env: str) -> List[str]:
    """
    Get all API keys for a provider from cache.
    
    Args:
        provider_or_env: Provider name or env var name
        
    Returns:
        List of all API keys (could be empty list)
    """
    env_name = _resolve_env_key(provider_or_env)
    return _KeyCache.get(env_name)


def get_next_key(provider_or_env: str) -> Optional[str]:
    """
    Get the next API key in rotation for a provider.
    
    This is the main function to use when making API calls.
    It automatically rotates through keys when called sequentially.
    When the last key is exhausted, it wraps around to the first key.
    
    Args:
        provider_or_env: Provider name or env var name
        
    Returns:
        The next key in rotation, or None if no keys are available
        
    Example:
        # First call returns first key
        key1 = get_next_key("groq")  # Returns key1
        
        # Second call returns second key (if available)
        key2 = get_next_key("groq")  # Returns key2
        
        # After all keys are used, wraps around
        key3 = get_next_key("groq")  # Returns key1 again
    """
    env_name = _resolve_env_key(provider_or_env)
    return _KeyCache.get_next_key(env_name)


def rotate_key(provider_or_env: str) -> Optional[str]:
    """
    Force rotate to the next key (call this when a key is exhausted).
    
    Use this when you detect that the current key has hit a rate limit
    or is no longer valid, and you want to immediately move to the next key
    without making a failed API call first.
    
    Args:
        provider_or_env: Provider name or env var name
        
    Returns:
        The next key in rotation, or None if no keys are available
    """
    env_name = _resolve_env_key(provider_or_env)
    return _KeyCache.rotate_to_next(env_name)


def get_key_status(provider_or_env: str) -> Dict[str, Any]:
    """
    Get the status of keys for a provider.
    
    Args:
        provider_or_env: Provider name or env var name
        
    Returns:
        Dict with key count, current index, and keys info
    """
    env_name = _resolve_env_key(provider_or_env)
    keys = _KeyCache.get(env_name)
    return {
        'env_name': env_name,
        'key_count': len(keys),
        'current_index': _KeyCache.get_current_index(env_name),
        'has_keys': len(keys) > 0
    }
