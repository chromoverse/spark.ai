# app/main.py
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.api_wrapper import include_api_routes
from app.config import settings
from app.socket import init_socket, sio, socket_app, connected_users
from app.db.mongo import connect_to_mongo, close_mongo_connection
from app.db.indexes import create_indexes
from app.kernel.observability.log_setup import configure_structured_logging
from app.kernel.runtime.kernel_runtime import get_kernel_runtime
from app.agent.execution_gateway import get_task_emitter

# Import auto-initializer system
import app.startup_registrations  # noqa: F401  — registers all init functions
from app.auto_initializer import run_all as run_all_initializers

from app.socket.task_handler import register_task_events

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
    
    # Wire socket handler to task emitter (for production mode)
    # This must happen after init_socket() below, or we register events now
    # register_task_events needs sio instance which is imported from app.socket
    # Let's register socket events
    task_handler = await register_task_events(sio, connected_users)
    get_task_emitter().set_socket_handler(task_handler)
    logger.info("🔌 Socket task handler wired to emitter")
    
    # Connect to database
    await connect_to_mongo()
    await create_indexes()
    logger.info(" Database connected")
    
    # Initialize WebSocket
    logger.info("📡 WebSocket server available at /ws")
    init_socket()
    logger.info("✅ WebSocket initialized")

    # Import ML runtime only after dependency bootstrap has completed.
    from app.ml import model_loader, embedding_worker, DEVICE
    app.state.model_loader = model_loader
    app.state.embedding_worker = embedding_worker
    app.state.ml_device = DEVICE
    
    # Load ML models
    logger.info("=" * 60)
    logger.info(f" Loading ML models on device: {DEVICE}")
    logger.info("=" * 60)
    
    success = model_loader.load_all_models()
    
    if success:
        logger.info(" All ML models loaded successfully")
        model_loader.warmup_models()
        logger.info(" Models warmed up - no cold start!")
    else:
        logger.warning("⚠️  Some ML models failed to load - check logs")
    

    
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
    logger.info(" ML models unloaded")
    
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
