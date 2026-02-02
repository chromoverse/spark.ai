"""
AI Provider Manager - Handles smart fallback between Gemini and OpenRouter
"""
import logging
import hashlib
import time
from typing import Dict, Tuple, Optional, Any
from enum import Enum

from app.ai.providers.gemini_client import GeminiClient
from app.ai.providers.openrouter_client import OpenRouterClient
from app.cache import redis_manager

logger = logging.getLogger(__name__)


class ModelProvider(Enum):
    """Available AI providers"""
    GEMINI = "gemini"
    OPENROUTER = "openrouter"


class QuotaError(Exception):
    """Raised when API quota is exhausted"""
    pass


class ProviderManager:
    """
    Manages AI provider selection and fallback logic.
    
    Priority: Gemini → OpenRouter
    """
    
    # Class-level cache for AI clients: {key_hash: client_instance}
    _client_cache: Dict[str, Any] = {}
    
    def _get_cache_key(self, user_id: str, provider: str, api_key: Optional[str]) -> str:
        """Generate a unique cache key for a client instance"""
        api_hash = hashlib.md5(api_key.encode()).hexdigest() if api_key else "default"
        return f"{user_id}:{provider}:{api_hash}"

    def __init__(self, user_details: Dict):
        """
        Initialize with user-specific details.
        
        Args:
            user_details: User data from Redis/MongoDB containing API keys and quota flags
        """
        self.user_details = user_details
        self.user_id = str(user_details.get('_id', 'unknown'))
        
        # --- Gemini Client ---
        gemini_api_key = user_details.get('gemini_api_key')
        gemini_quota = user_details.get('is_gemini_api_quota_reached', False)
        gemini_cache_key = self._get_cache_key(self.user_id, "gemini", gemini_api_key)
        
        if gemini_cache_key in self._client_cache:
            self.gemini_client = self._client_cache[gemini_cache_key]
            # Sync quota state from details (in case it was updated elsewhere)
            self.gemini_client.quota_reached = gemini_quota
        else:
            self.gemini_client = GeminiClient(
                api_key=gemini_api_key,
                quota_reached=gemini_quota
            )
            self._client_cache[gemini_cache_key] = self.gemini_client
        
        # --- OpenRouter Client ---
        or_api_key = user_details.get('openrouter_api_key')
        or_quota = user_details.get('is_openrouter_api_quota_reached', False)
        or_cache_key = self._get_cache_key(self.user_id, "openrouter", or_api_key)
        
        if or_cache_key in self._client_cache:
            self.openrouter_client = self._client_cache[or_cache_key]
            self.openrouter_client.quota_reached = or_quota
        else:
            self.openrouter_client = OpenRouterClient(
                api_key=or_api_key,
                quota_reached=or_quota
            )
            self._client_cache[or_cache_key] = self.openrouter_client
    
    def _is_quota_error(self, error: Exception) -> bool:
        """
        Detect if error is quota-related.
        
        Checks for:
        - 429 status codes
        - "quota", "rate limit", "exhausted" in error messages
        """
        error_str = str(error).lower()
        quota_keywords = [
            'quota', 'rate limit', 'resource has been exhausted',
            'too many requests', '429', 'rate_limit_exceeded'
        ]
        
        if getattr(error, 'status_code', None) == 429:
            return True
        
        return any(keyword in error_str for keyword in quota_keywords)
    
    async def call_with_fallback(
        self,
        prompt: str,
        model_name: Optional[str] = None
    ) -> Tuple[str, ModelProvider]:
        """
        Call AI provider with automatic fallback.
        """
        
        # --- Try Gemini First ---
        # Check if quota block has expired in Redis
        if self.gemini_client.quota_reached:
            block_key = f"user:{self.user_id}:quota_blocked:gemini"
            if not await redis_manager.get(block_key):
                logger.info(f"🔄 Gemini quota block expired for user {self.user_id}, resetting status")
                await self._update_quota_status(ModelProvider.GEMINI, quota_reached=False)

        if not self.gemini_client.quota_reached:
            try:
                logger.info(f"🔹 Attempting Gemini for user {self.user_id}")
                response = self.gemini_client.send_message(prompt)
                logger.info(f"✅ Gemini success for user {self.user_id}")
                return response, ModelProvider.GEMINI
            
            except QuotaError as e:
                logger.warning(f"🚨 Gemini quota exhausted for user {self.user_id}: {e}")
                await self._update_quota_status(ModelProvider.GEMINI, quota_reached=True)
                # Fall through to OpenRouter
            
            except Exception as e:
                logger.error(f"❌ Gemini failed (non-quota): {e}", exc_info=True)
                if self._is_quota_error(e):
                    await self._update_quota_status(ModelProvider.GEMINI, quota_reached=True)
                # Fall through to OpenRouter
        
        else:
            logger.info(f"⏭️  Skipping Gemini (quota reached for user {self.user_id})")
        
        # --- Fallback to OpenRouter ---
        # Check if quota block has expired in Redis
        if self.openrouter_client.quota_reached:
            block_key = f"user:{self.user_id}:quota_blocked:openrouter"
            if not await redis_manager.get(block_key):
                logger.info(f"🔄 OpenRouter quota block expired for user {self.user_id}, resetting status")
                await self._update_quota_status(ModelProvider.OPENROUTER, quota_reached=False)

        if not self.openrouter_client.quota_reached:
            try:
                logger.info(f"🔸 Attempting OpenRouter for user {self.user_id}")
                response = self.openrouter_client.send_message(prompt, model_name)
                logger.info(f"✅ OpenRouter success for user {self.user_id}")
                return response, ModelProvider.OPENROUTER
            
            except QuotaError as e:
                logger.error(f"🚨 OpenRouter quota exhausted for user {self.user_id}: {e}")
                await self._update_quota_status(ModelProvider.OPENROUTER, quota_reached=True)
                raise Exception(
                    "All API quotas exhausted. Please add your own API keys in settings or try again later."
                )
            
            except Exception as e:
                logger.error(f"❌ OpenRouter failed: {e}", exc_info=True)
                if self._is_quota_error(e):
                    await self._update_quota_status(ModelProvider.OPENROUTER, quota_reached=True)
                raise Exception(f"OpenRouter API error: {str(e)}")
        
        else:
            logger.error(f"❌ All quotas exhausted for user {self.user_id}")
            raise Exception(
                "All API quotas exhausted. Please add your own API keys in settings or contact support."
            )
    
    async def _update_quota_status(self, provider: ModelProvider, quota_reached: bool):
        """
        Update quota status in Redis and handle auto-reset TTL.
        """
        try:
            # Update in-memory flag
            if provider == ModelProvider.GEMINI:
                self.gemini_client.quota_reached = quota_reached
                self.user_details['is_gemini_api_quota_reached'] = quota_reached
            else:
                self.openrouter_client.quota_reached = quota_reached
                self.user_details['is_openrouter_api_quota_reached'] = quota_reached
            
            # Persist to Redis (permanent user details)
            await redis_manager.set_user_details(self.user_id, self.user_details)
            
            # Manage temporary quota block key in Redis
            block_key = f"user:{self.user_id}:quota_blocked:{provider.value}"
            if quota_reached:
                # Default TTL: 1 hour for 429s, 24 hours for daily reset
                # We can adjust this based on error type later, but 1 hour is a good safety buffer
                ttl = 3600 
                await redis_manager.set(block_key, "blocked", ex=ttl)
                logger.info(f"⏸️  Set {provider.value} quota block for {ttl}s")
            else:
                await redis_manager.delete(block_key)
                logger.info(f"✨ Removed {provider.value} quota block")

            logger.info(f"✅ Updated {provider.value} quota status in user details: {quota_reached}")
        
        except Exception as e:
            logger.error(f"Failed to update quota status: {e}", exc_info=True)
        
        