"""
Application Lifespan Handler
----------------------------
Manages startup and shutdown events.
Initializes and warms up the inference service on startup.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.services.inference_service import get_inference_service
from app.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI.
    
    Startup:
        - Initializes InferenceService
        - Downloads model/binary if missing
        - Warms up model for faster first response
        
    Shutdown:
        - Cleans up resources
    
    The inference service is stored in app.state for access by endpoints.
    """
    # -----------------------
    # STARTUP
    # -----------------------
    print("\n" + "=" * 60)
    print("🚀 Starting Reasoning LLM Microservice")
    print("=" * 60)
    
    # Create and setup inference service
    inference_service = get_inference_service()
    
    try:
        # Setup downloads model and binary if needed
        inference_service.setup(
            auto_download_binary=settings.auto_download_binary
        )
        
        # Warmup model if enabled
        if settings.warmup_on_startup:
            inference_service.warmup()
        
        # Store in app state for endpoint access
        app.state.inference_service = inference_service
        
        print("\n" + "=" * 60)
        print(f"✅ Server ready at http://{settings.host}:{settings.port}")
        print(f"📖 API docs at http://{settings.host}:{settings.port}/docs")
        print("=" * 60 + "\n")
        
    except Exception as e:
        print(f"\n❌ Startup failed: {e}")
        print("The server will start but inference will not be available.")
        app.state.inference_service = None
    
    # -----------------------
    # YIELD (app runs here)
    # -----------------------
    yield
    
    # -----------------------
    # SHUTDOWN
    # -----------------------
    print("\n👋 Shutting down Reasoning LLM Microservice...")
    
    if app.state.inference_service:
        print("Stopping inference service...")
        app.state.inference_service.shutdown()
        app.state.inference_service = None
    
    print("✅ Shutdown complete")
