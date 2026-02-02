"""
Gemini API Client - Handles Gemini-specific API calls
Uses Google's native generativeai SDK with Gemini 2.5 Flash
"""
import logging
from typing import Optional
import google.generativeai as genai
from app.config import settings

logger = logging.getLogger(__name__)


class GeminiClient:
    """
    Handles all Gemini API interactions.
    
    Supports both:
    - System-wide default API key (from settings)
    - User-specific API keys (from user profile)
    """
    
    def __init__(self, api_key: Optional[str] = None, quota_reached: bool = False):
        """
        Initialize Gemini client.
        
        Args:
            api_key: User-specific API key (optional, falls back to system default)
            quota_reached: Whether quota is already exhausted
        """
        self.quota_reached = quota_reached
        
        # Use user key if provided, otherwise fall back to system default
        self.api_key = api_key or settings.gemini_api_key
        
        if not self.api_key:
            logger.warning("No Gemini API key configured (user or system)")
            self.quota_reached = True
            self.model = None
        else:
            try:
                genai.configure(api_key=self.api_key) # type: ignore
                # Use gemini-2.5-flash (newest, fastest, free tier available)
                self.model = genai.GenerativeModel(settings.gemini_model_name) # type: ignore
                logger.info(f"✅ Gemini client initialized with {settings.gemini_model_name} (using {'user' if api_key else 'system'} key)")
            except Exception as e:
                logger.error(f"Failed to initialize Gemini: {e}")
                self.model = None
                self.quota_reached = True
    
    def send_message(
        self,
        prompt: str,
        temperature: float = 0.7
    ) -> str:
        """
        Send a message to Gemini API.
        
        Args:
            prompt: The user prompt
            temperature: Sampling temperature (0.0 to 2.0)
        
        Returns:
            AI response text
        
        Raises:
            QuotaError: If quota is exhausted
            Exception: For other API errors
        """
        from app.ai.providers.manager import QuotaError
        
        if not self.model:
            raise QuotaError("Gemini client not initialized (no API key)")
        
        if self.quota_reached:
            raise QuotaError("Gemini quota already exhausted")
        
        try:
            # Configure generation settings
            generation_config = {
                "temperature": temperature,
                "top_p": 0.95,
                "top_k": 40,
                "max_output_tokens": 8192,
            }
            
            response = self.model.generate_content(
                prompt,
                generation_config=generation_config # type: ignore
            )
            
            # Check if response is valid
            if not response or not response.text:
                raise ValueError("Empty response from Gemini")
            
            logger.debug(f"Gemini response: {response.text[:100]}...")
            return response.text
        
        except Exception as e:
            error_str = str(e).lower()
            
            # Check for quota/rate limit errors (429, resource exhausted, billing issues)
            if any(kw in error_str for kw in [
                'quota', 'rate limit', '429', 'exhausted', 
                'resource_exhausted', 'billing', 'exceeded'
            ]):
                logger.warning(f"Gemini quota exhausted: {e}")
                self.quota_reached = True
                raise QuotaError(f"Gemini quota error: {e}")
            
            # Check for safety/content filter blocks
            if 'safety' in error_str or 'blocked' in error_str:
                logger.warning(f"Gemini content blocked: {e}")
                raise ValueError(f"Content blocked by safety filters: {e}")
            
            # Log and re-raise other errors
            logger.error(f"Gemini API error: {e}", exc_info=True)
            raise