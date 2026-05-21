"""
Intelligent LLM Router — Use-case-aware provider selection with fallback chains.

Replaces the old flat Groq→Gemini→OpenRouter chain with per-use-case routing.
Zero routing overhead: pure dict lookup to get the provider chain for a use-case.

Usage:
    from app.ai.providers.router import routed_chat, routed_stream

    # Chat with use-case routing
    response, provider = await routed_chat("streaming", messages)

    # Stream with use-case routing
    async for chunk in routed_stream("streaming", messages):
        print(chunk)
"""
import asyncio
import logging
import time
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from app.ai.providers.base_client import BaseClient, AllKeysExhaustedError
from app.ai.providers.routing_config import ROUTING_TABLE, UNIVERSAL_FALLBACK
from app.utils.async_utils import with_retry

logger = logging.getLogger(__name__)

QUOTA_BLOCK_TTL: int = 3600  # 1 hour


class _ProviderRegistry:
    """
    Lazy-initialized registry of all provider client instances.
    Each provider is instantiated once and reused across all use-cases.
    """
    _instances: Dict[str, BaseClient] = {}
    _initialized: bool = False

    @classmethod
    def get(cls, name: str) -> Optional[BaseClient]:
        if not cls._initialized:
            cls._init_all()
        return cls._instances.get(name)

    @classmethod
    def all_providers(cls) -> Dict[str, BaseClient]:
        if not cls._initialized:
            cls._init_all()
        return cls._instances

    @classmethod
    def _init_all(cls) -> None:
        from app.ai.providers.groq_client import GroqClient
        from app.ai.providers.gemini_client import GeminiClient
        from app.ai.providers.openrouter_client import OpenRouterClient
        from app.ai.providers.cerebras_client import CerebrasClient
        from app.ai.providers.sambanova_client import SambaNovaClient
        from app.ai.providers.mistral_client import MistralClient

        cls._instances = {
            "groq": GroqClient(),
            "gemini": GeminiClient(),
            "openrouter": OpenRouterClient(),
            "cerebras": CerebrasClient(),
            "sambanova": SambaNovaClient(),
            "mistral": MistralClient(),
        }
        cls._initialized = True
        available = [n for n, p in cls._instances.items() if p.is_available]
        logger.info(f"🚀 Provider registry ready. Available: {available}")


class IntelligentRouter:
    """
    Routes LLM calls to the best provider based on use-case.

    Flow:
    1. Look up use-case in ROUTING_TABLE → get ordered provider chain
    2. Walk the chain: skip blocked/unavailable providers
    3. If all use-case providers fail → try UNIVERSAL_FALLBACK
    """

    _instance: Optional["IntelligentRouter"] = None

    def __new__(cls) -> "IntelligentRouter":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init = False
        return cls._instance

    def __init__(self) -> None:
        if self._init:
            return
        self._init = True
        self._quota_blocked: Dict[str, float] = {}
        logger.info("🧠 Intelligent Router initialized")

    def _is_blocked(self, provider_name: str) -> bool:
        blocked_at = self._quota_blocked.get(provider_name)
        if blocked_at is None:
            return False
        elapsed = time.time() - blocked_at
        if elapsed >= QUOTA_BLOCK_TTL:
            del self._quota_blocked[provider_name]
            provider = _ProviderRegistry.get(provider_name)
            if provider:
                provider.reset_keys()
            return False
        return True

    def _block(self, provider_name: str) -> None:
        self._quota_blocked[provider_name] = time.time()
        logger.warning(f"🚫 {provider_name} blocked for {QUOTA_BLOCK_TTL}s")

    def _get_chain(self, use_case: str) -> List[Tuple[str, str]]:
        """Get provider chain for use-case, falling back to streaming if unknown."""
        return ROUTING_TABLE.get(use_case, ROUTING_TABLE["streaming"])

    async def chat(
        self,
        use_case: str,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Tuple[str, str]:
        """
        Route a chat call through the use-case's provider chain.
        Returns (response_text, provider_name).
        """
        chain = self._get_chain(use_case)
        last_error: Optional[Exception] = None

        # Try use-case chain
        result = await self._try_chain(chain, messages, temperature, max_tokens, stream=False)
        if result is not None:
            return result  # type: ignore

        # Universal fallback
        logger.warning(f"⚠️ All {use_case} providers failed, trying universal fallback")
        result = await self._try_chain(UNIVERSAL_FALLBACK, messages, temperature, max_tokens, stream=False)
        if result is not None:
            return result  # type: ignore

        raise AllProvidersExhaustedError(
            f"All providers exhausted for use_case={use_case}. No fallback available."
        )

    async def stream(
        self,
        use_case: str,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """
        Route a stream call through the use-case's provider chain.
        Yields text chunks.
        """
        chain = self._get_chain(use_case)

        # Try use-case chain
        yielded = False
        async for chunk in self._try_chain_stream(chain, messages, temperature, max_tokens):
            yielded = True
            yield chunk
        if yielded:
            return

        # If we get here, use-case chain failed entirely
        logger.warning(f"⚠️ All {use_case} providers failed (stream), trying universal fallback")
        async for chunk in self._try_chain_stream(UNIVERSAL_FALLBACK, messages, temperature, max_tokens):
            yielded = True
            yield chunk
        if yielded:
            return

        raise AllProvidersExhaustedError(
            f"All providers exhausted for use_case={use_case} (stream)."
        )

    async def _try_chain(
        self,
        chain: List[Tuple[str, str]],
        messages: List[Dict[str, str]],
        temperature: Optional[float],
        max_tokens: Optional[int],
        stream: bool = False,
    ) -> Optional[Tuple[str, str]]:
        """Try each provider in chain for chat. Returns (text, provider) or None."""
        for provider_name, model in chain:
            if self._is_blocked(provider_name):
                continue
            provider = _ProviderRegistry.get(provider_name)
            if not provider or not provider.is_available:
                continue

            try:
                response = await asyncio.wait_for(
                    provider.llm_chat(
                        messages=messages, model=model,
                        temperature=temperature, max_tokens=max_tokens,
                    ),
                    timeout=45.0,
                )
                logger.info(f"✅ {provider_name}/{model} → {len(response)} chars")
                return response, provider_name
            except asyncio.TimeoutError:
                logger.warning(f"⏰ {provider_name}/{model} timed out (45s), trying next")
            except AllKeysExhaustedError:
                self._block(provider_name)
            except Exception as e:
                logger.error(f"❌ {provider_name}/{model}: {e}")
        return None

    async def _try_chain_stream(
        self,
        chain: List[Tuple[str, str]],
        messages: List[Dict[str, str]],
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> AsyncIterator[str]:
        """Try each provider in chain for streaming. Yields chunks from first success."""
        for provider_name, model in chain:
            if self._is_blocked(provider_name):
                continue
            provider = _ProviderRegistry.get(provider_name)
            if not provider or not provider.is_available:
                continue

            try:
                chunks_yielded = False
                async for chunk in provider.llm_stream(
                    messages=messages, model=model,
                    temperature=temperature, max_tokens=max_tokens,
                ):
                    chunks_yielded = True
                    yield chunk
                if chunks_yielded:
                    logger.info(f"✅ {provider_name}/{model} stream complete")
                    return
            except AllKeysExhaustedError:
                self._block(provider_name)
            except Exception as e:
                logger.error(f"❌ {provider_name}/{model} stream: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Health check for all providers."""
        status: Dict[str, Any] = {}
        for name, provider in _ProviderRegistry.all_providers().items():
            blocked_at = self._quota_blocked.get(name)
            remaining = max(0.0, QUOTA_BLOCK_TTL - (time.time() - blocked_at)) if blocked_at else 0.0
            status[name] = {
                **provider.status,
                "blocked": self._is_blocked(name),
                "blocked_remaining_s": round(remaining, 1),
            }
        return status


class AllProvidersExhaustedError(Exception):
    pass


# ═══════════════════════════════════════════════════════════════
#  Module-level singleton + convenience functions
# ═══════════════════════════════════════════════════════════════

_router: IntelligentRouter = IntelligentRouter()


async def routed_chat(
    use_case: str,
    messages: List[Dict[str, str]],
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> Tuple[str, str]:
    """
    Chat with intelligent use-case routing.

    Args:
        use_case: One of "streaming", "reasoning", "lightweight", "content_generate", "summarize"
        messages: Chat messages
        temperature: Optional override
        max_tokens: Optional override

    Returns:
        (response_text, provider_name)
    """
    return await _router.chat(use_case, messages, temperature, max_tokens)


async def routed_stream(
    use_case: str,
    messages: List[Dict[str, str]],
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> AsyncIterator[str]:
    """
    Stream with intelligent use-case routing.

    Args:
        use_case: One of "streaming", "reasoning", "lightweight", "content_generate", "summarize"
        messages: Chat messages

    Yields:
        Text chunks
    """
    async for chunk in _router.stream(use_case, messages, temperature, max_tokens):
        yield chunk


def get_router() -> IntelligentRouter:
    """Get the singleton router instance."""
    return _router
