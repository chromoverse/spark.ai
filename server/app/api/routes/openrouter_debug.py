"""
Debug route for testing OpenRouter API
Add this to your routes for debugging
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import logging

from app.ai.providers.openrouter_client import OpenRouterClient
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/debug/openrouter", tags=["Debug"])


class TestRequest(BaseModel):
    prompt: str = "Say hello"
    model: Optional[str] = None
    temperature: float = 0.7


@router.get("/status")
async def openrouter_status():
    """Check OpenRouter configuration and status"""
    client = OpenRouterClient()
    
    return {
        "api_key_configured": bool(client.api_key),
        "api_key_length": len(client.api_key) if client.api_key else 0,
        "api_key_preview": f"{client.api_key[:8]}...{client.api_key[-4:]}" if client.api_key else None,
        "default_model": client.DEFAULT_MODEL,
        "settings_model": settings.openrouter_reasoning_model_name,
        "client_initialized": client.client is not None,
        "quota_reached": client.quota_reached
    }


@router.post("/test")
async def test_openrouter(request: TestRequest):
    """Test OpenRouter API with a simple prompt"""
    client = OpenRouterClient()
    
    if not client.client:
        raise HTTPException(
            status_code=500,
            detail="OpenRouter client not initialized - check API key"
        )
    
    try:
        logger.info(f"🧪 Testing OpenRouter with prompt: '{request.prompt}'")
        
        response = client.send_message(
            prompt=request.prompt,
            model=request.model,
            temperature=request.temperature
        )
        
        return {
            "success": True,
            "response": response,
            "response_length": len(response),
            "model_used": request.model or client.DEFAULT_MODEL
        }
    
    except Exception as e:
        logger.error(f"❌ OpenRouter test failed: {e}", exc_info=True)
        
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


@router.get("/models")
async def list_openrouter_models():
    """List available OpenRouter models"""
    client = OpenRouterClient()
    
    if not client.client:
        raise HTTPException(
            status_code=500,
            detail="OpenRouter client not initialized"
        )
    
    try:
        models = client.get_available_models()
        
        return {
            "success": True,
            "count": len(models),
            "models": models[:20],  # First 20 for readability
            "all_models": models
        }
    
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@router.post("/test-models")
async def test_multiple_models():
    """Test multiple models to see which ones work"""
    client = OpenRouterClient()
    
    # Common models to test
    test_models = [
        "openai/gpt-3.5-turbo",
        "anthropic/claude-2",
        "google/palm-2-chat-bison",
        "meta-llama/llama-2-70b-chat",
        settings.openrouter_reasoning_model_name
    ]
    
    results = []
    
    for model in test_models:
        if not model:
            continue
            
        try:
            logger.info(f"🧪 Testing model: {model}")
            
            response = client.send_message(
                prompt="Say 'test' and nothing else.",
                model=model,
                temperature=0.0
            )
            
            results.append({
                "model": model,
                "success": True,
                "response": response,
                "response_length": len(response)
            })
            
        except Exception as e:
            results.append({
                "model": model,
                "success": False,
                "error": str(e)
            })
    
    successful = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]
    
    return {
        "total_tested": len(results),
        "successful": len(successful),
        "failed": len(failed),
        "results": results,
        "working_models": [r["model"] for r in successful]
    }