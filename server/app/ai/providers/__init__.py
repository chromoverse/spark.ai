"""
AI Providers Package

Handles intelligent routing between different AI providers with automatic fallback.
"""

from app.ai.providers.manager import ProviderManager, ModelProvider, QuotaError
from app.ai.providers.gemini_client import GeminiClient
from app.ai.providers.openrouter_client import OpenRouterClient

__all__ = [
    'ProviderManager',
    'ModelProvider',
    'QuotaError',
    'GeminiClient',
    'OpenRouterClient'
]