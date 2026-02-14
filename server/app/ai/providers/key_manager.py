"""
API Key Manager — Utility for persisting LLM provider API keys.

Saves keys to Windows system environment variables (User-level)
so they survive reboots without needing a .env file.

Features:
    - One-shot bulk load: reads ALL provider keys from the Windows registry
      in a single handle open, then serves from memory forever.
    - Auto-syncs into os.environ so BaseClient._load_keys() finds keys
      via os.getenv() without any extra I/O.

Usage:
    from app.ai.providers.key_manager import register_api_key, list_registered_keys

    # Add a key
    register_api_key("groq", "gsk_abc123...")

    # Add by env var name directly
    register_api_key("GEMINI_API_KEY", "AIzaSy...")

    # List all registered keys (instant — served from cache)
    list_registered_keys()
"""
import os
import sys
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# ── Provider name → env var mapping ──
PROVIDER_ENV_MAP: Dict[str, str] = {
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


# ═══════════════════════════════════════════════════════════════
#  In-memory key cache — loads from registry ONCE, then instant
# ═══════════════════════════════════════════════════════════════

class _KeyCache:
    """
    Module-level cache for API keys.

    On first access, bulk-reads every PROVIDER_ENV_MAP key from the
    Windows User registry in a single handle open/close and populates
    os.environ.  All subsequent reads are pure dict lookups — zero I/O.
    """

    _loaded: bool = False
    _cache: Dict[str, Optional[str]] = {}

    # ── public API ──

    @classmethod
    def get_all(cls) -> Dict[str, Optional[str]]:
        """Return the full {env_name: raw_value|None} dict (loads on first call)."""
        if not cls._loaded:
            cls._bulk_load()
        return cls._cache

    @classmethod
    def get(cls, env_name: str) -> Optional[str]:
        """Get a single key value from cache."""
        if not cls._loaded:
            cls._bulk_load()
        return cls._cache.get(env_name)

    @classmethod
    def set(cls, env_name: str, value: str) -> None:
        """Update cache + os.environ after a registry write."""
        if not cls._loaded:
            cls._bulk_load()
        cls._cache[env_name] = value
        os.environ[env_name] = value

    @classmethod
    def delete(cls, env_name: str) -> None:
        """Remove from cache + os.environ after a registry delete."""
        if not cls._loaded:
            cls._bulk_load()
        cls._cache[env_name] = None
        os.environ.pop(env_name, None)

    # ── internals ──

    @classmethod
    def _bulk_load(cls) -> None:
        """
        Read ALL provider keys from the Windows User registry in one pass.

        Opens the HKCU\\Environment key once, reads every env var in
        PROVIDER_ENV_MAP, then closes it.  Also syncs found values into
        os.environ so that os.getenv() works everywhere else.
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

                        cls._cache[env_name] = raw

                        # Sync into os.environ so os.getenv() works
                        if raw:
                            os.environ[env_name] = raw
                finally:
                    winreg.CloseKey(reg_key)
            except OSError as e:
                logger.warning(f"⚠️  Could not open registry Environment key: {e}")
                # Fallback: read from os.environ directly
                for env_name in env_names:
                    raw = os.getenv(env_name)
                    cls._cache[env_name] = raw
        else:
            # Non-Windows: just read os.environ
            for env_name in env_names:
                cls._cache[env_name] = os.getenv(env_name)

        cls._loaded = True
        loaded_count = sum(1 for v in cls._cache.values() if v)
        logger.info(
            f"🔑 KeyCache: bulk-loaded {loaded_count}/{len(env_names)} keys "
            f"from {'registry' if sys.platform == 'win32' else 'environ'}"
        )


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


def register_api_key(provider_or_env: str, api_key: str) -> str:
    """
    Save an API key to the system environment (persistent).

    Args:
        provider_or_env: Provider name ('groq', 'gemini', 'openrouter')
                         or env var name ('GROQ_API_KEY')
        api_key: The actual API key string

    Returns:
        The env var name that was set

    Example:
        register_api_key("groq", "gsk_abc123...")
        register_api_key("GEMINI_API_KEY", "AIzaSy...")
    """
    env_name = _resolve_env_key(provider_or_env)
    api_key = api_key.strip()

    if not api_key:
        raise ValueError("API key cannot be empty")

    # Store as plain key (no brackets — avoids the Windows quote-stripping issue)
    _set_windows_env(env_name, api_key)

    # Update cache + os.environ immediately (no stale reads)
    _KeyCache.set(env_name, api_key)

    logger.info(f"✅ Saved {env_name} to system environment ({api_key[:8]}...)")
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


def list_registered_keys() -> Dict[str, Optional[str]]:
    """
    List all provider API keys (instant — served from cache).

    Returns:
        Dict mapping env var name → masked key (or None if not set)

    Example:
        {
            'GROQ_API_KEY': 'gsk_HmMn****CP5',
            'GEMINI_API_KEY': None,
            'OPENROUTER_API_KEY': 'sk-or-v1****3b2',
        }
    """
    result: Dict[str, Optional[str]] = {}
    cached = _KeyCache.get_all()

    for env_name in PROVIDER_ENV_MAP.values():
        raw = cached.get(env_name)
        if raw:
            # Mask the key for display: show first 8 + last 3 chars
            if len(raw) > 15:
                masked = f"{raw[:8]}****{raw[-3:]}"
            else:
                masked = f"{raw[:4]}****"
            result[env_name] = masked
        else:
            result[env_name] = None

    return result


def get_raw_key(provider_or_env: str) -> Optional[str]:
    """
    Get the raw (unmasked) API key for a provider from cache.

    This is useful when you need the actual key value without
    going through os.getenv() or the registry.
    """
    env_name = _resolve_env_key(provider_or_env)
    return _KeyCache.get(env_name)
