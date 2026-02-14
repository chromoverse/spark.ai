"""
Base LLM Client — Abstract base class for all AI provider clients.

Features:
- JSON array key parsing from os.getenv() (e.g. '["key1","key2"]')
- Round-robin key rotation with failure tracking
- Thread-safe key ops via asyncio.Lock
- Common quota detection (DRY — subclasses only add provider-specific patterns)
- Abstract llm_chat() and llm_stream() with auto-retry across keys
"""
import os
import json
import logging
import asyncio
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any, Set, AsyncIterator, AsyncGenerator

logger = logging.getLogger(__name__)


# ─────────────────────────── Exceptions ───────────────────────────

class QuotaError(Exception):
    """Raised when a single API key hits quota/rate limit."""
    pass


class AllKeysExhaustedError(Exception):
    """Raised when every key for a provider has failed."""
    pass


# ─────────────────────────── Common quota keywords ───────────────────────────

_COMMON_QUOTA_KEYWORDS: List[str] = [
    "quota", "rate limit", "rate_limit", "429",
    "too many requests", "exhausted", "exceeded",
    "insufficient", "credits", "billing",
]


# ─────────────────────────── Base Client ───────────────────────────

class BaseClient(ABC):
    """
    Abstract base for LLM provider clients.

    Subclasses MUST implement:
        _create_client(api_key)   — build the SDK client for one key
        _do_chat(client, ...)     — execute a non-streaming chat call
        _do_stream(client, ...)   — execute a streaming chat call (yield chunks)

    Subclasses MAY override:
        _extra_quota_keywords()   — return provider-specific quota keywords
    """

    def __init__(
        self,
        provider_name: str,
        env_key: str,
        default_model: str = "",
        default_temperature: float = 0.7,
        default_max_tokens: int = 4096,
    ) -> None:
        self.provider_name: str = provider_name
        self.env_key: str = env_key
        self.default_model: str = default_model
        self.default_temperature: float = default_temperature
        self.default_max_tokens: int = default_max_tokens

        # Key management
        self._keys: List[str] = self._load_keys()
        self._failed_keys: Set[str] = set()
        self._current_key_index: int = 0
        self._clients: Dict[str, Any] = {}  # api_key -> SDK client cache
        self._lock: asyncio.Lock = asyncio.Lock()  # thread-safe key ops

        if not self._keys:
            logger.warning(f"⚠️  No API keys found for {provider_name} (env: {env_key})")
        else:
            logger.info(f"🔑 {provider_name}: loaded {len(self._keys)} key(s)")

    def __repr__(self) -> str:
        avail = len(self._keys) - len(self._failed_keys)
        return f"<{self.__class__.__name__} provider={self.provider_name!r} keys={avail}/{len(self._keys)}>"

    # ────────────────────────── Key Management ──────────────────────────

    def _load_keys(self) -> List[str]:
        """
        Load API keys from environment variable (os.getenv only).

        Supports formats:
            '["key1","key2"]'   — JSON array (preferred)
            "['key1','key2']"   — JSON array with single quotes
            '[key1,key2]'       — bracket-wrapped, no quotes (Windows strips them)
            'key1'              — plain single key
        """
        raw = os.getenv(self.env_key, "")
        if not raw or not raw.strip():
            return []

        raw = raw.strip()

        # Handle bracket-wrapped values
        if raw.startswith("[") and raw.endswith("]"):
            # 1. Try proper JSON array: ["key1","key2"]
            try:
                keys = json.loads(raw)
                if isinstance(keys, list):
                    return [str(k).strip() for k in keys if k and str(k).strip()]
            except json.JSONDecodeError:
                pass

            # 2. Try single-quote JSON: ['key1','key2']
            try:
                fixed = raw.replace("'", '"')
                keys = json.loads(fixed)
                if isinstance(keys, list):
                    return [str(k).strip() for k in keys if k and str(k).strip()]
            except json.JSONDecodeError:
                pass

            # 3. Bracket-no-quotes: [key1,key2]
            #    Windows SetEnvironmentVariable strips the inner quotes
            inner = raw[1:-1].strip()
            if inner:
                parts = [k.strip().strip("'\"") for k in inner.split(",")]
                keys_list = [k for k in parts if k]
                if keys_list:
                    logger.info(
                        f"🔑 Parsed {self.env_key} as bracket-wrapped list "
                        f"({len(keys_list)} key(s))"
                    )
                    return keys_list

        # Fallback: treat as single key
        return [raw]
    def _get_active_key(self) -> Optional[str]:
        """Get the current active key (skipping failed ones)."""
        if not self._keys:
            return None

        for _ in range(len(self._keys)):
            key = self._keys[self._current_key_index % len(self._keys)]
            if key not in self._failed_keys:
                return key
            self._current_key_index = (self._current_key_index + 1) % len(self._keys)

        return None  # All keys failed

    def _rotate_key(self) -> Optional[str]:
        """Move to the next key in rotation."""
        if not self._keys:
            return None
        self._current_key_index = (self._current_key_index + 1) % len(self._keys)
        return self._get_active_key()

    def _mark_key_failed(self, key: str) -> None:
        """Mark a key as failed (quota exhausted / invalid)."""
        self._failed_keys.add(key)
        logger.warning(
            f"🔴 {self.provider_name}: key {key[:8]}... marked as failed "
            f"({len(self._failed_keys)}/{len(self._keys)} failed)"
        )

    def reset_keys(self) -> None:
        """Reset all failed keys — called when quota TTL expires."""
        self._failed_keys.clear()
        self._current_key_index = 0
        logger.info(f"🔄 {self.provider_name}: all keys reset")

    @property
    def all_keys_exhausted(self) -> bool:
        """True if every key has been marked as failed."""
        return len(self._failed_keys) >= len(self._keys) if self._keys else True

    @property
    def is_available(self) -> bool:
        """True if this provider has at least one working key."""
        return bool(self._keys) and not self.all_keys_exhausted

    @property
    def status(self) -> Dict[str, Any]:
        """Return a snapshot of this provider's status."""
        return {
            "provider": self.provider_name,
            "total_keys": len(self._keys),
            "failed_keys": len(self._failed_keys),
            "available": self.is_available,
            "model": self.default_model,
        }

    # ────────────────────────── Client Caching ──────────────────────────

    def _get_or_create_client(self, api_key: str) -> Any:
        """Get cached SDK client or create new one for the given key."""
        if api_key not in self._clients:
            self._clients[api_key] = self._create_client(api_key)
        return self._clients[api_key]

    # ────────────────────────── Quota Detection (DRY) ──────────────────────────

    def _is_quota_error(self, error: Exception) -> bool:
        """
        Check if an error indicates quota/rate-limit exhaustion.

        Base implementation checks common keywords + HTTP 429 status.
        Subclasses can override _extra_quota_keywords() to add provider-specific patterns.
        """
        # Check HTTP status code
        status_code = getattr(error, "status_code", None)
        if status_code == 429:
            return True

        error_str = str(error).lower()
        all_keywords = _COMMON_QUOTA_KEYWORDS + self._extra_quota_keywords()
        return any(kw in error_str for kw in all_keywords)

    def _extra_quota_keywords(self) -> List[str]:
        """Override in subclass to add provider-specific quota keywords."""
        return []

    # ────────────────────────── Abstract Methods ──────────────────────────

    @abstractmethod
    def _create_client(self, api_key: str) -> Any:
        """Create the underlying SDK client for a given API key."""
        ...

    @abstractmethod
    async def _do_chat(
        self,
        client: Any,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Execute a chat completion. Return the response text."""
        ...

    @abstractmethod
    async def _do_stream(
        self,
        client: Any,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> AsyncGenerator[str, None]:
        """
        Execute a streaming chat completion. Yield text chunks.

        Implementations must be async generators (use `yield`).
        """
        yield ""  # pragma: no cover — abstract, makes this a valid async generator

    # ────────────────────────── Public API ──────────────────────────

    async def llm_chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Send a chat request with automatic key rotation on failure.

        Raises:
            AllKeysExhaustedError: if every key has been tried and failed
        """
        model = model or self.default_model
        temperature = temperature if temperature is not None else self.default_temperature
        max_tokens = max_tokens or self.default_max_tokens

        last_error: Optional[Exception] = None

        for _ in range(len(self._keys)):
            async with self._lock:
                key = self._get_active_key()
            if key is None:
                break

            try:
                client = self._get_or_create_client(key)
                response = await self._do_chat(client, messages, model, temperature, max_tokens)
                return response

            except Exception as e:
                last_error = e
                if self._is_quota_error(e):
                    logger.warning(f"⚠️  {self.provider_name} quota hit on key {key[:8]}...: {e}")
                else:
                    logger.error(f"❌ {self.provider_name} error on key {key[:8]}...: {e}")
                async with self._lock:
                    self._mark_key_failed(key)
                    self._rotate_key()

        raise AllKeysExhaustedError(
            f"All {len(self._keys)} keys exhausted for {self.provider_name}. "
            f"Last error: {last_error}"
        )

    async def llm_stream(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Stream a chat response with automatic key rotation on failure.

        Yields:
            str: Text chunks as they arrive

        Raises:
            AllKeysExhaustedError: if every key has been tried and failed
        """
        model = model or self.default_model
        temperature = temperature if temperature is not None else self.default_temperature
        max_tokens = max_tokens or self.default_max_tokens

        last_error: Optional[Exception] = None

        for _ in range(len(self._keys)):
            async with self._lock:
                key = self._get_active_key()
            if key is None:
                break

            try:
                client = self._get_or_create_client(key)
                stream = self._do_stream(client, messages, model, temperature, max_tokens)
                async for chunk in stream:
                    yield chunk
                return  # Stream completed successfully

            except Exception as e:
                last_error = e
                if self._is_quota_error(e):
                    logger.warning(
                        f"⚠️  {self.provider_name} stream quota hit on key {key[:8]}...: {e}"
                    )
                else:
                    logger.error(f"❌ {self.provider_name} stream error on key {key[:8]}...: {e}")
                async with self._lock:
                    self._mark_key_failed(key)
                    self._rotate_key()

        raise AllKeysExhaustedError(
            f"All {len(self._keys)} keys exhausted for {self.provider_name} (stream). "
            f"Last error: {last_error}"
        )
