"""
OpenRouter API Client - Fixed with better error handling
"""
import logging
from typing import Optional, Dict, Any
from openai import OpenAI
from app.config import settings

logger = logging.getLogger(__name__)


class OpenRouterClient:
    """
    Handles all OpenRouter API interactions with robust error handling.
    
    Supports both:
    - System-wide default API key (from settings)
    - User-specific API keys (from user profile)
    """
    
    DEFAULT_MODEL = settings.openrouter_reasoning_model_name 
    BASE_URL = "https://openrouter.ai/api/v1"
    
    def __init__(self, api_key: Optional[str] = None, quota_reached: bool = False):
        """
        Initialize OpenRouter client.
        
        Args:
            api_key: User-specific API key (optional, falls back to system default)
            quota_reached: Whether quota is already exhausted
        """
        self.quota_reached = quota_reached
        
        # Use user key if provided, otherwise fall back to system default
        self.api_key = api_key or settings.openrouter_api_key
        
        if not self.api_key:
            logger.warning("No OpenRouter API key configured (user or system)")
            self.quota_reached = True
            self.client = None
        else:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.BASE_URL,
                timeout=30.0,  # Add timeout
                max_retries=2  # Add retry logic
            )
            logger.info(f"✅ OpenRouter client initialized (using {'user' if api_key else 'system'} key)")
    
    def send_message(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> str:
        """
        Send a message to OpenRouter API with improved error handling.
        
        Args:
            prompt: The user prompt
            model: Model name (defaults to settings or class default)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
        
        Returns:
            AI response text
        
        Raises:
            QuotaError: If quota is exhausted
            Exception: For other API errors
        """
        from app.ai.providers.manager import QuotaError
        
        if not self.client:
            raise QuotaError("OpenRouter client not initialized (no API key)")
        
        if self.quota_reached:
            raise QuotaError("OpenRouter quota already exhausted")
        
        # Use provided model, or fall back to settings, or use default
        model_to_use = settings.openrouter_reasoning_model_name or self.DEFAULT_MODEL
        logger.error(f"🔥 MODEL BEING SENT TO OPENROUTER = [{model_to_use}] (type={type(model_to_use)})")

        # Validate model name
        if not model_to_use:
            raise ValueError("No model specified and no default model configured")
        
        try:
            logger.info(f"🔸 Sending to OpenRouter: model={model_to_use}, prompt_length={len(prompt)}")
            
            # Build request parameters
            request_params: Dict[str, Any] = {
                "model": model_to_use,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
            }
            
            # Add max_tokens if specified
            if max_tokens:
                request_params["max_tokens"] = max_tokens
            
            # Add extra headers
            request_params["extra_headers"] = {
                "HTTP-Referer": "https://siddhantyadav.com.np",
                "X-Title": "Siddy Coddy",
            }
            
            # Make API call
            completion = self.client.chat.completions.create(**request_params)
            
            # Debug: Log full completion object
            logger.debug(f"OpenRouter completion object: {completion}")
            
            # Check if completion has choices
            if not completion.choices:
                logger.error("❌ OpenRouter returned no choices")
                logger.error(f"Full response: {completion}")
                raise ValueError("OpenRouter returned no choices in response")
            
            # Check if first choice exists
            if len(completion.choices) == 0:
                logger.error("❌ OpenRouter choices array is empty")
                raise ValueError("OpenRouter choices array is empty")
            
            # Get the message
            message = completion.choices[0].message
            
            if not message:
                logger.error("❌ OpenRouter message is None")
                logger.error(f"Choice: {completion.choices[0]}")
                raise ValueError("OpenRouter message is None")
            
            # Get content
            response = message.content
            
            # Check for empty response
            if response is None:
                logger.error("❌ OpenRouter content is None")
                logger.error(f"Message: {message}")
                
                # Check finish_reason for clues
                finish_reason = completion.choices[0].finish_reason
                logger.error(f"Finish reason: {finish_reason}")
                
                if finish_reason == "content_filter":
                    raise ValueError("Response blocked by content filter")
                elif finish_reason == "length":
                    raise ValueError("Response truncated due to length limit")
                else:
                    raise ValueError(f"Empty response from OpenRouter (finish_reason: {finish_reason})")
            
            if not response.strip():
                logger.error("❌ OpenRouter returned empty string")
                logger.error(f"Full completion: {completion}")
                raise ValueError("OpenRouter returned empty string")
            
            # Log usage info if available
            if hasattr(completion, 'usage') and completion.usage:
                logger.info(f"📊 OpenRouter usage: {completion.usage}")
            
            logger.info(f"✅ OpenRouter response received: {len(response)} chars")
            logger.debug(f"Response preview: {response[:200]}...")
            
            return response
        
        except Exception as e:
            error_str = str(e).lower()
            
            # Log full error for debugging
            logger.error(f"❌ OpenRouter API error: {e}", exc_info=True)
            
            # Check for quota-specific errors
            quota_keywords = [
                'quota', 'rate limit', '429', 'exhausted', 'credits',
                'insufficient', 'balance', 'exceeded'
            ]
            
            if any(kw in error_str for kw in quota_keywords):
                logger.error(f"🚨 Detected quota error in OpenRouter response")
                raise QuotaError(f"OpenRouter quota error: {e}")
            
            # Check for content filter
            if 'content_filter' in error_str or 'content filter' in error_str:
                raise ValueError(f"OpenRouter content filter triggered: {e}")
            
            # Re-raise with more context
            raise Exception(f"OpenRouter API error: {str(e)}")
    
    def test_connection(self) -> bool:
        """
        Test if the OpenRouter connection works.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            response = self.send_message(
                prompt="Say 'test' and nothing else.",
                temperature=0.0,
                max_tokens=10
            )
            return bool(response and len(response) > 0)
        except Exception as e:
            logger.error(f"OpenRouter connection test failed: {e}")
            return False
    
    def get_available_models(self) -> list:
        """
        Get list of available models from OpenRouter.
        
        Returns:
            List of model names
        """
        try:
            # OpenRouter models endpoint
            import requests
            response = requests.get(
                "https://openrouter.ai/api/v1/models",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "HTTP-Referer": "https://siddhantyadav.com.np"
                }
            )
            
            if response.status_code == 200:
                models = response.json().get("data", [])
                return [model.get("id") for model in models]
            else:
                logger.error(f"Failed to fetch models: {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Error fetching models: {e}")
            return []