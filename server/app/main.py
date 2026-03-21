# app/main.py
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.api_wrapper import include_api_routes
from app.config import settings
from app.socket import init_socket, socket_app
from app.db.mongo import connect_to_mongo, close_mongo_connection
from app.db.indexes import create_indexes
from app.kernel.observability.log_setup import configure_structured_logging
from app.kernel.runtime.kernel_runtime import get_kernel_runtime
from app.startup_state import startup_state

# Import auto-initializer system
import app.startup_registrations  # noqa: F401  — registers all init functions
from app.auto_initializer import run_all as run_all_initializers

# Configure logging
configure_structured_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ========== STARTUP ==========
    logger.info("=" * 60)
    logger.info("🚀 Application starting up...")
    logger.info("=" * 60)
    
    # Run all registered startup initializers (cache, keys, TTS, Agent System, etc.)
    await run_all_initializers()
    
    # Connect to database
    await connect_to_mongo()
    await create_indexes()
    logger.info(" Database connected")
    
    # Initialize WebSocket
    logger.info("📡 WebSocket server available at /ws")
    init_socket()
    logger.info("✅ WebSocket initialized")

    # ML runtime state is initialized by startup registrations.
    app.state.model_loader = startup_state.model_loader
    app.state.embedding_worker = startup_state.embedding_worker
    app.state.ml_device = startup_state.ml_device
    app.state.embedding_ready = startup_state.embedding_ready
    app.state.pinecone_service = startup_state.pinecone_service
    app.state.pinecone_ready = startup_state.pinecone_ready

    if settings.environment == "PRODUCTION":
        logger.info("Pinecone startup warmup ready=%s", bool(app.state.pinecone_ready))

    if app.state.model_loader is None:
        logger.info("Skipping local ML model initialization (env=%s)", settings.environment)
    elif settings.environment == "DESKTOP" and not bool(app.state.embedding_ready):
        logger.warning(
            "⚠️ Embedding startup prime not ready; query-context will use fallback until warm."
        )
    

    
    logger.info("=" * 60)
    logger.info(" Application startup complete")
    logger.info(" Server is ready to handle requests!")
    logger.info("=" * 60)
    
    yield  # Application is running
    
    # ========== SHUTDOWN ==========
    logger.info("=" * 60)
    logger.info(" Application shutting down...")
    logger.info("=" * 60)
    
    # Flush kernel persistence
    await get_kernel_runtime().stop()
    logger.info(" Kernel runtime stopped")

    # Cleanup database
    await close_mongo_connection()
    logger.info(" Database disconnected")
    
    # Cleanup ML resources
    embedding_worker = getattr(app.state, "embedding_worker", None)
    model_loader = getattr(app.state, "model_loader", None)
    if embedding_worker is not None:
        embedding_worker.shutdown()
    if model_loader is not None:
        model_loader.unload_all_models()
    if model_loader is not None or embedding_worker is not None:
        logger.info(" ML models unloaded")
    else:
        logger.info(" ML teardown skipped (not initialized)")
    
    # Cleanup other resources
    from app.utils.async_utils import cleanup_executor
    cleanup_executor()
    logger.info(" Application shutdown complete")
    logger.info("=" * 60)


# Create FastAPI app
app = FastAPI(
    title="AI Assistant API",
    description="FastAPI backend with ML models and WebSocket support",
    version="2.0.0",
    lifespan=lifespan
)

# Add CORS
app.add_middleware(
    CORSMiddleware,
    # Frontend URLs are controlled via config FRONTEND_URLS (comma-separated).
    allow_origins=settings.frontend_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include all HTTP API routes through unified wrapper
include_api_routes(app)

# Mount WebSocket
app.mount("/socket.io", socket_app)
