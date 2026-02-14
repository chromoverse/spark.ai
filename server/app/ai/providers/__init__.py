"""
AI Providers Package

Clean public API for LLM interactions with automatic provider fallback.

Usage:
    from app.ai.providers import llm_chat, llm_stream

    # Chat (returns response + provider name)
    response, provider = await llm_chat([{"role": "user", "content": "Hello"}])

    # Stream
    async for chunk in llm_stream([{"role": "user", "content": "Tell me a story"}]):
        print(chunk, end="", flush=True)
"""

from app.ai.providers.base_client import BaseClient, QuotaError, AllKeysExhaustedError
from app.ai.providers.manager import (
    LLMManager,
    AllProvidersExhaustedError,
    llm_chat,
    llm_stream,
    get_llm_manager,
)
from app.ai.providers.key_manager import (
    register_api_key,
    remove_api_key,
    list_registered_keys,
    get_raw_key,
)

__all__ = [
    # Public API functions
    "llm_chat",
    "llm_stream",
    # Manager
    "LLMManager",
    "get_llm_manager",
    # Key management
    "register_api_key",
    "remove_api_key",
    "list_registered_keys",
    # Exceptions
    "QuotaError",
    "AllKeysExhaustedError",
    "AllProvidersExhaustedError",
    # Base class (for extending with new providers)
    "BaseClient",
]