# app/main.py
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import chat, tts, stt, auth, ml_test, openrouter_debug
from app.socket import init_socket, sio, socket_app, connected_users
from app.db.mongo import connect_to_mongo, close_mongo_connection
from app.db.indexes import create_indexes

# Import ML components
from app.ml import model_loader, embedding_worker, DEVICE, MODELS_CONFIG

# Import auto-initializer system
import app.startup_registrations  # noqa: F401  — registers all init functions
from app.auto_initializer import run_all as run_all_initializers

# below both imports needed for task handling in client
from app.socket.task_handler import register_task_events
from app.agent.core.task_emitter import get_task_emitter

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
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
    # Actually register_task_events needs sio instance which is imported from app.socket
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
    
    # Cleanup database
    await close_mongo_connection()
    logger.info(" Database disconnected")
    
    # Cleanup ML resources
    embedding_worker.shutdown()
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
    allow_origins=["*", "http://localhost:5123"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {
        "message": "Your AI assistant is ready!",
        "device": DEVICE,
        "socket": "/socket.io",
        "docs": "/docs"
    }


@app.get("/health")
def health_check():
    """Health check endpoint"""
    orchestrator = get_orchestrator()
    registry = get_tool_registry()
    
    return {
        "status": "healthy",
        "device": DEVICE,
        "models_loaded": list(model_loader._models.keys()),
        "tools_loaded": len(registry.tools),
        "active_users": len(orchestrator.states)
    }


@app.get("/ml/status")
def ml_status():
    """Check ML models status"""
    return {
        "device": DEVICE,
        "models_loaded": list(model_loader._models.keys()),
        "models_available": list(MODELS_CONFIG.keys())
    }


# Orchestration status endpoint
@app.get("/orchestration/status")
def orchestration_status():
    """Check orchestration system status"""
    registry = get_tool_registry()
    orchestrator = get_orchestrator()
    
    return {
        "registry": {
            "total_tools": len(registry.tools),
            "server_tools": len(registry.server_tools),
            "client_tools": len(registry.client_tools),
            "categories": list(registry.categories.keys())
        },
        "orchestrator": {
            "active_users": len(orchestrator.states),
            "total_tasks": sum(
                len(state.tasks) for state in orchestrator.states.values()
            )
        }
    }


# Include routes
app.include_router(chat.router)
app.include_router(tts.router)
app.include_router(stt.router)
app.include_router(auth.router)
app.include_router(ml_test.router)
app.include_router(openrouter_debug.router)

# Mount WebSocket
app.mount("/socket.io", socket_app)