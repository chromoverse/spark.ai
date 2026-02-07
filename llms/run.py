"""
Server Entry Script
-------------------
Run this script to start the FastAPI server.

Usage:
    python run.py
    
Or with uvicorn directly:
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
"""

import uvicorn
from app.core.config import settings


def main():
    """
    Start the Uvicorn server with configured settings.
    
    Environment variables can override defaults:
        - HOST: Server host (default: 0.0.0.0)
        - PORT: Server port (default: 8000)
        - DEBUG: Enable reload mode (default: false)
    """
    print("\n" + "=" * 50)
    print("🎯 Reasoning LLM Microservice")
    print("=" * 50)
    print(f"Host: {settings.host}")
    print(f"Port: {settings.port}")
    print(f"Debug: {settings.debug}")
    print(f"Model: {settings.model_name}")
    print("=" * 50 + "\n")
    
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="info"
    )


if __name__ == "__main__":
    main()
