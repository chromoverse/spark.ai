"""
API Key Manager — Unified key storage for LLM providers.

Storage:
    - Windows Registry: {username}:{ENV_NAME} (local persistence)
    - MongoDB: api_keys.{provider} (cloud/mobile accessible)
    - In-memory _KeyCache (runtime, zero I/O)

Usage:
    from app.ai.providers.key_manager import register_api_key_unified, get_next_key

    # Store keys (saves to registry + mongo + memory)
    await register_api_key_unified("siddthecoder", "groq", ["key1", "key2"], user_id="abc123")

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
    "cerebras": "CEREBRAS_API_KEY",
    "sambanova": "SAMBANOVA_API_KEY",
    "mistral": "MISTRAL_API_KEY",
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
    # User-scoped keys: {user_id: {env_name: ["key1", ...]}}
    _user_keys: Dict[str, Dict[str, List[str]]] = {}
    _user_rotation_index: Dict[str, Dict[str, int]] = {}
    _active_user_id: Optional[str] = None

    # ── user-scoped key API ──

    @classmethod
    def set_active_user(cls, user_id: Optional[str]) -> None:
        """Set the active user whose keys take priority."""
        cls._active_user_id = user_id

    @classmethod
    def load_user_keys(cls, user_id: str, provider: str, keys: List[str]) -> None:
        """Load keys for a specific user+provider. These take priority over system keys."""
        env_name = PROVIDER_ENV_MAP.get(provider.lower(), provider.upper())
        if user_id not in cls._user_keys:
            cls._user_keys[user_id] = {}
            cls._user_rotation_index[user_id] = {}
        clean = [k.strip() for k in keys if k.strip()]
        cls._user_keys[user_id][env_name] = clean
        cls._user_rotation_index[user_id][env_name] = 0

    @classmethod
    def clear_user_keys(cls, user_id: str) -> None:
        """Remove all cached keys for a user."""
        cls._user_keys.pop(user_id, None)
        cls._user_rotation_index.pop(user_id, None)
        if cls._active_user_id == user_id:
            cls._active_user_id = None

    # ── public API ──

    @classmethod
    def get_all(cls) -> Dict[str, List[str]]:
        """Return the full {env_name: [keys]} dict (loads on first call)."""
        if not cls._loaded:
            cls._bulk_load()
        return cls._cache

    @classmethod
    def get(cls, env_name: str) -> List[str]:
        """Get keys: user-scoped first, then system fallback."""
        if not cls._loaded:
            cls._bulk_load()
        # Priority: active user's keys
        if cls._active_user_id:
            user_keys = cls._user_keys.get(cls._active_user_id, {}).get(env_name, [])
            if user_keys:
                return user_keys
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
        Get the next key in rotation. User keys take priority over system keys.
        """
        if not cls._loaded:
            cls._bulk_load()
        
        # Check user keys first
        if cls._active_user_id:
            user_keys = cls._user_keys.get(cls._active_user_id, {}).get(env_name, [])
            if user_keys:
                idx_map = cls._user_rotation_index.get(cls._active_user_id, {})
                idx = idx_map.get(env_name, 0)
                key = user_keys[idx]
                idx_map[env_name] = (idx + 1) % len(user_keys)
                return key
        
        # Fallback to system keys
        keys = cls._cache.get(env_name, [])
        if not keys:
            return None
        current_index = cls._rotation_index.get(env_name, 0)
        key = keys[current_index]
        cls._rotation_index[env_name] = (current_index + 1) % len(keys)
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

        Looks for keys in format: {username}:{ENV_NAME}
        e.g. "siddthecoder:GROQ_API_KEY"
        
        Loads the first match found for each env_name.
        """
        env_names = list(PROVIDER_ENV_MAP.values())

        if sys.platform == "win32":
            import winreg

            try:
                reg_key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Environment",
                    0,
                    winreg.KEY_QUERY_VALUE | winreg.KEY_READ,
                )
                try:
                    # Enumerate all values, find ones matching *:{ENV_NAME}
                    found: Dict[str, str] = {}
                    i = 0
                    while True:
                        try:
                            name, value, _ = winreg.EnumValue(reg_key, i)
                            i += 1
                            # Check if this matches username:ENV_NAME pattern
                            for env_name in env_names:
                                if name == env_name or name.endswith(f":{env_name}"):
                                    if env_name not in found and value:
                                        found[env_name] = str(value).strip()
                        except OSError:
                            break

                    for env_name in env_names:
                        raw = found.get(env_name)
                        keys = cls._parse_keys(raw)
                        cls._cache[env_name] = keys
                        cls._rotation_index[env_name] = 0
                        if keys:
                            os.environ[env_name] = keys[0]
                finally:
                    winreg.CloseKey(reg_key)
            except OSError as e:
                logger.warning(f"⚠️  Could not open registry Environment key: {e}")
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


# ═══════════════════════════════════════════════════════════════
#  User-scoped key management (NO legacy — api_keys dict only)
# ═══════════════════════════════════════════════════════════════

def activate_user_keys(user_id: str, user_data: Dict[str, Any]) -> None:
    """
    Load user's API keys into priority layer.
    Reads ONLY from api_keys: {provider: [keys]}.
    """
    api_keys_obj = user_data.get("api_keys") or {}
    for provider in PROVIDER_ENV_MAP:
        keys = api_keys_obj.get(provider) or []
        if keys:
            _KeyCache.load_user_keys(user_id, provider, keys)
    _KeyCache.set_active_user(user_id)
    loaded = {p: len(api_keys_obj.get(p, [])) for p in PROVIDER_ENV_MAP if api_keys_obj.get(p)}
    logger.info(f"🔑 Activated user keys for {user_id}: {loaded}")


def deactivate_user_keys(user_id: str) -> None:
    """Remove user keys and fall back to system keys."""
    _KeyCache.clear_user_keys(user_id)
    logger.info(f"🔑 Deactivated user keys for {user_id}")


# ═══════════════════════════════════════════════════════════════
#  Unified key registration — THE ONLY way to store keys.
#  Registry format: {username}:{ENV_NAME}
#  MongoDB format:  api_keys.{provider}
# ═══════════════════════════════════════════════════════════════

async def register_api_key_unified(
    username: str,
    provider: str,
    keys: Union[str, List[str]],
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Unified key registration — saves to Windows Registry AND MongoDB.

    Args:
        username: REQUIRED. Used as registry prefix: "{username}:GROQ_API_KEY"
        provider: Provider name ('groq', 'gemini', 'cerebras', etc.)
        keys: Single key string or list of keys
        user_id: MongoDB _id. If provided, persists to DB too.

    Returns:
        Dict with status info
    """
    if not username or not username.strip():
        raise ValueError("username is required for key registration")

    provider_lower = provider.strip().lower()
    if provider_lower not in PROVIDER_ENV_MAP:
        raise ValueError(f"Unknown provider: '{provider}'. Use one of: {list(PROVIDER_ENV_MAP.keys())}")

    key_list = [keys.strip()] if isinstance(keys, str) else [k.strip() for k in keys if k.strip()]
    if not key_list:
        raise ValueError("At least one API key is required")

    env_name = PROVIDER_ENV_MAP[provider_lower]
    registry_name = f"{username.strip()}:{env_name}"

    # 1. Windows Registry: username:ENV_NAME
    stored_value = json.dumps(key_list) if len(key_list) > 1 else key_list[0]
    _set_windows_env(registry_name, stored_value)
    _KeyCache.set(env_name, key_list)

    # 2. MongoDB: api_keys.{provider}
    if user_id:
        from app.db.mongo import get_db
        from bson import ObjectId
        db = get_db()
        await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {f"api_keys.{provider_lower}": key_list}},
        )

    # 3. In-memory priority layer
    if user_id:
        _KeyCache.load_user_keys(user_id, provider_lower, key_list)

    logger.info(f"🔑 {registry_name} → {len(key_list)} key(s) [registry{'+ mongo' if user_id else ''}]")
    return {"provider": provider_lower, "registry_name": registry_name, "key_count": len(key_list)}


async def register_all_keys_unified(
    username: str,
    keys_map: Dict[str, Union[str, List[str]]],
    user_id: Optional[str] = None,
) -> Dict[str, int]:
    """
    Bulk register keys for multiple providers.

    Args:
        username: REQUIRED.
        keys_map: {provider: keys}
        user_id: Optional MongoDB _id.
    """
    results: Dict[str, int] = {}
    for provider, keys in keys_map.items():
        provider_lower = provider.strip().lower()
        if provider_lower not in PROVIDER_ENV_MAP:
            continue
        key_list = [keys.strip()] if isinstance(keys, str) else [k.strip() for k in keys if k.strip()]
        if not key_list:
            continue
        await register_api_key_unified(username, provider_lower, key_list, user_id=user_id)
        results[provider_lower] = len(key_list)
    return results
