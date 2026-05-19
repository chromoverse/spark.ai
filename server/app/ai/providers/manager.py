"""
LLM Manager — Singleton provider manager with automatic fallback and quota caching.

Fallback chain: Groq → Gemini → OpenRouter

Features:
- Singleton instance (initialized once at module load)
- Walks the provider chain on failure
- Tracks quota exhaustion in-memory with TTL-based auto-reset
- Extensible: add new providers by appending to _providers list
"""
import asyncio
import logging
import time
from typing import Any, List, Dict, Optional, AsyncIterator, Tuple

from app.ai.providers.base_client import BaseClient, AllKeysExhaustedError
from app.ai.providers.groq_client import GroqClient
from app.ai.providers.gemini_client import GeminiClient
from app.ai.providers.openrouter_client import OpenRouterClient
from app.utils.async_utils import with_retry

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

    def _model_belongs_to(self, provider: BaseClient, model: Optional[str]) -> bool:
        """Check if the requested model is native to this provider."""
        if not model:
            return True  # no model specified, use default
        # Each provider uses its own default — if the model matches, it belongs
        if model == provider.default_model:
            return True
        # Provider-specific prefixes
        name = provider.provider_name.lower()
        if name == "groq" and ("llama" in model or "mixtral" in model or "gemma" in model or "gpt-oss" in model):
            return True
        if name == "gemini" and "gemini" in model:
            return True
        if name == "openrouter":
            return True  # OpenRouter supports everything
        return False

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

            # Only pass caller's model to the first provider that matches it.
            # Fallback providers use their own default model.
            use_model = model if self._model_belongs_to(provider, model) else None

            try:
                logger.info(f"🔹 Trying {provider.provider_name}...")
                response = await with_retry(
                    lambda p=provider, m=use_model: p.llm_chat(
                        messages=messages,
                        model=m,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    ),
                    attempts=3,
                    base_delay=0.2,
                    name=f"llm-chat:{provider.provider_name}",
                    do_not_retry_on=(AllKeysExhaustedError,),
                )
                logger.info(f"✅ {provider.provider_name} success ({len(response)} chars)")
                return response, provider.provider_name

            except AllKeysExhaustedError as e:
                logger.warning(f"🔴 {provider.provider_name}: all keys exhausted")
                self._block_provider(provider)
                last_error = e

            except Exception as e:
                logger.error(f"❌ {provider.provider_name} unexpected error after retries: {e}")
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

        # Per-provider retry policy:
        # • Up to 3 attempts per provider before falling back to the next.
        # • If chunks have already been streamed to the caller, do NOT retry —
        #   that would replay tokens. Move directly to the next provider.
        # • AllKeysExhaustedError is non-retryable: block this provider and
        #   move on without consuming retry budget.
        per_provider_attempts = 3

        for provider in self._providers:
            if self._is_provider_blocked(provider):
                continue

            if not provider.is_available:
                continue

            # Only pass caller's model to the provider that owns it.
            # Fallback providers use their own default model.
            use_model = model if self._model_belongs_to(provider, model) else None

            should_skip_provider = False
            for attempt in range(1, per_provider_attempts + 1):
                chunks_yielded = False
                chunk_count = 0
                try:
                    logger.info(
                        f"🔹 Streaming via {provider.provider_name} "
                        f"(attempt {attempt}/{per_provider_attempts})..."
                    )
                    async for chunk in provider.llm_stream(
                        messages=messages,
                        model=use_model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    ):
                        chunks_yielded = True
                        chunk_count += 1
                        yield chunk

                    logger.info(
                        f"✅ {provider.provider_name} stream done ({chunk_count} chunks)"
                    )
                    return  # full stream completed successfully

                except AllKeysExhaustedError as e:
                    logger.warning(
                        f"🔴 {provider.provider_name}: all keys exhausted (stream)"
                    )
                    self._block_provider(provider)
                    last_error = e
                    should_skip_provider = True
                    break  # don't retry this provider, move to next

                except Exception as e:
                    last_error = e
                    if chunks_yielded:
                        logger.error(
                            f"❌ {provider.provider_name} mid-stream error after "
                            f"{chunk_count} chunks: {e}; moving to next provider"
                        )
                        should_skip_provider = True
                        break  # cannot safely retry — try next provider

                    if attempt >= per_provider_attempts:
                        logger.error(
                            f"❌ {provider.provider_name} stream exhausted "
                            f"{per_provider_attempts} attempts: {e}"
                        )
                        break  # exhaust this provider

                    delay = 0.2 * (2 ** (attempt - 1))
                    logger.warning(
                        f"⚠️ {provider.provider_name} stream attempt "
                        f"{attempt}/{per_provider_attempts} failed ({e}); "
                        f"retrying in {delay*1000:.0f}ms"
                    )
                    await asyncio.sleep(delay)

            # outer for loop continues to next provider regardless

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