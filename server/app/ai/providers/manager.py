"""
LLM Manager — Singleton provider manager with automatic fallback and quota caching.

Fallback chain: Groq → Gemini → OpenRouter

Features:
- Singleton instance (initialized once at module load)
- Walks the provider chain on failure
- Tracks quota exhaustion in-memory with TTL-based auto-reset
- Extensible: add new providers by appending to _providers list
"""
import logging
import time
from typing import Any, List, Dict, Optional, AsyncIterator, Tuple

from app.ai.providers.base_client import BaseClient, AllKeysExhaustedError
from app.ai.providers.groq_client import GroqClient
from app.ai.providers.gemini_client import GeminiClient
from app.ai.providers.openrouter_client import OpenRouterClient

logger = logging.getLogger(__name__)

# Quota block TTL in seconds (1 hour)
QUOTA_BLOCK_TTL: int = 3600


class AllProvidersExhaustedError(Exception):
    """Raised when every provider in the chain has failed."""
    pass


class LLMManager:
    """
    Singleton LLM manager — the single entry point for all LLM calls.

    Usage:
        from app.ai.providers import llm_chat, llm_stream

        response, provider = await llm_chat([{"role": "user", "content": "Hello"}])

        async for chunk in llm_stream([{"role": "user", "content": "Hi"}]):
            print(chunk)
    """

    _instance: Optional["LLMManager"] = None

    def __new__(cls) -> "LLMManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False  # type: ignore[attr-defined]
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:  # type: ignore[has-type]
            return
        self._initialized: bool = True

        logger.info("🚀 Initializing LLM Manager (singleton)...")

        # ── Provider chain (order = priority) ──
        self._providers: List[BaseClient] = [
            GroqClient(),
            GeminiClient(),
            OpenRouterClient(),
        ]

        # ── In-memory quota block tracker ──
        # provider_name -> timestamp when blocked (auto-expires after TTL)
        self._quota_blocked: Dict[str, float] = {}

        available = [p.provider_name for p in self._providers if p.is_available]
        logger.info(f"✅ LLM Manager ready. Available providers: {available}")

    # ────────────────────────── Quota Cache ──────────────────────────

    def _is_provider_blocked(self, provider: BaseClient) -> bool:
        """Check if a provider is temporarily blocked due to quota exhaustion."""
        blocked_at = self._quota_blocked.get(provider.provider_name)
        if blocked_at is None:
            return False

        elapsed = time.time() - blocked_at
        if elapsed >= QUOTA_BLOCK_TTL:
            # TTL expired — reset provider
            logger.info(
                f"🔄 {provider.provider_name} quota block expired "
                f"({elapsed:.0f}s), resetting keys"
            )
            del self._quota_blocked[provider.provider_name]
            provider.reset_keys()
            return False

        remaining = QUOTA_BLOCK_TTL - elapsed
        logger.debug(f"⏸️  {provider.provider_name} still blocked ({remaining:.0f}s remaining)")
        return True

    def _block_provider(self, provider: BaseClient) -> None:
        """Mark a provider as quota-blocked with current timestamp."""
        self._quota_blocked[provider.provider_name] = time.time()
        logger.warning(
            f"🚫 {provider.provider_name} blocked for {QUOTA_BLOCK_TTL}s (all keys exhausted)"
        )

    # ────────────────────────── Public API ──────────────────────────

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Tuple[str, str]:
        """
        Send a chat request with automatic provider fallback.

        Returns:
            Tuple[str, str]: (response_text, provider_name)

        Raises:
            AllProvidersExhaustedError: if every provider in the chain fails
        """
        last_error: Optional[Exception] = None

        for provider in self._providers:
            if self._is_provider_blocked(provider):
                continue

            if not provider.is_available:
                continue

            try:
                logger.info(f"🔹 Trying {provider.provider_name}...")
                response = await provider.llm_chat(
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                logger.info(f"✅ {provider.provider_name} success ({len(response)} chars)")
                return response, provider.provider_name

            except AllKeysExhaustedError as e:
                logger.warning(f"🔴 {provider.provider_name}: all keys exhausted")
                self._block_provider(provider)
                last_error = e

            except Exception as e:
                logger.error(f"❌ {provider.provider_name} unexpected error: {e}")
                last_error = e

        raise AllProvidersExhaustedError(
            f"All providers exhausted. Last error: {last_error}. "
            "Please add valid API keys or try again later."
        )

    async def stream(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """
        Stream a chat response with automatic provider fallback.

        Yields:
            str: Text chunks

        Raises:
            AllProvidersExhaustedError: if every provider in the chain fails
        """
        last_error: Optional[Exception] = None

        for provider in self._providers:
            if self._is_provider_blocked(provider):
                continue

            if not provider.is_available:
                continue

            try:
                logger.info(f"🔹 Streaming via {provider.provider_name}...")
                chunk_count = 0
                async for chunk in provider.llm_stream(
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ):
                    chunk_count += 1
                    yield chunk

                logger.info(f"✅ {provider.provider_name} stream done ({chunk_count} chunks)")
                return  # stream completed

            except AllKeysExhaustedError as e:
                logger.warning(f"🔴 {provider.provider_name}: all keys exhausted (stream)")
                self._block_provider(provider)
                last_error = e

            except Exception as e:
                logger.error(f"❌ {provider.provider_name} stream error: {e}")
                last_error = e

        raise AllProvidersExhaustedError(
            f"All providers exhausted (stream). Last error: {last_error}. "
            "Please add valid API keys or try again later."
        )

    def get_status(self) -> Dict[str, Any]:
        """Return current status of all providers (for debugging / health check)."""

        status: Dict[str, Any] = {}
        for p in self._providers:
            blocked_at = self._quota_blocked.get(p.provider_name)
            remaining = 0.0
            if blocked_at is not None:
                remaining = max(0.0, QUOTA_BLOCK_TTL - (time.time() - blocked_at))

            status[p.provider_name] = {
                **p.status,
                "blocked": self._is_provider_blocked(p),
                "blocked_remaining_s": round(remaining, 1),
            }
        return status


# ════════════════════════════════════════════════════════════════
#  Module-level singleton + convenience functions
# ════════════════════════════════════════════════════════════════

_manager: LLMManager = LLMManager()


async def llm_chat(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> Tuple[str, str]:
    """
    Quick helper — chat with automatic provider fallback.

    Returns:
        Tuple[str, str]: (response_text, provider_name)

    Example:
        response, provider = await llm_chat([{"role": "user", "content": "Hi"}])
    """
    return await _manager.chat(messages, model, temperature, max_tokens)


async def llm_stream(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> AsyncIterator[str]:
    """
    Quick helper — stream with automatic provider fallback.

    Example:
        async for chunk in llm_stream([{"role": "user", "content": "Hi"}]):
            print(chunk)
    """
    async for chunk in _manager.stream(messages, model, temperature, max_tokens):
        yield chunk


def get_llm_manager() -> LLMManager:
    """Get the singleton LLMManager instance."""
    return _manager