"""
FastAPI Application Entry Point
-------------------------------
Main application factory with routing and middleware.

Endpoints:
    - GET /health - Health check
    - POST /api/v1/llm/reasoning/chat - Chat with LLM
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.lifespan import lifespan
from app.core.config import settings
from app.api.v1.llm.router import router as llm_router
from app.api.v1.llm.schemas import HealthResponse


# -----------------------
# Create FastAPI App
# -----------------------
app = FastAPI(
    title="Reasoning LLM Microservice",
    description="""
    A high-performance LLM inference microservice using llama.cpp.
    
    ## Features
    - 🚀 Fast inference with llama.cpp
    - 🔥 Model warmup on startup
    - 🎯 Auto GPU/CPU detection
    - 📥 Automatic model/binary downloads
    
    ## Endpoint
    - **POST /api/v1/llm/reasoning/chat** - Chat with the reasoning model
    """,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)


# -----------------------
# CORS Middleware
# -----------------------
# Allow all origins in development (restrict in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------
# Include Routers
# -----------------------
# Mount LLM router at /api/v1/llm
app.include_router(
    llm_router,
    prefix="/api/v1/llm"
)


# -----------------------
# Health Check Endpoint
# -----------------------
@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["health"],
    summary="Health check endpoint"
)
async def health_check() -> HealthResponse:
    """
    Check service health and model readiness.
    
    Returns:
        Health status with model readiness info
    """
    service = getattr(app.state, 'inference_service', None)
    
    if service and service.is_ready:
        return HealthResponse(
            status="healthy",
            model_ready=True,
            device=service.device_type
        )
    else:
        return HealthResponse(
            status="unhealthy",
            model_ready=False,
            device=None
        )


@app.get("/", include_in_schema=False)
async def root():
    """Root endpoint redirect to docs."""
    return {
        "message": "Reasoning LLM Microservice",
        "docs": "/docs",
        "health": "/health",
        "chat": "/api/v1/llm/reasoning/chat"
    }
