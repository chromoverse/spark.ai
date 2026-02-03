# app/main.py
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import chat, tts, stt, auth, ml_test, openrouter_debug
from app.socket.socket_server import sio, connected_users, socket_app
from app.socket.socket_utils import init_socket_utils
from app.db.mongo import connect_to_mongo, close_mongo_connection
from app.db.indexes import create_indexes

# Import ML components
from app.ml import model_loader, embedding_worker, DEVICE, MODELS_CONFIG

# Import orchestration system
from app.registry.loader import load_tool_registry, get_tool_registry
from app.core.orchestrator import init_orchestrator, get_orchestrator
from app.core.execution_engine import init_execution_engine, get_execution_engine
from app.core.server_executor import init_server_executor, get_server_executor
# below both imports needed for task handling in client
from app.socket.task_handler import register_task_events
from app.core.task_emitter import get_task_emitter

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
    
    # Load Tool Registry FIRST
    logger.info("\n Loading Tool Registry...")
    try:
        load_tool_registry()
        registry = get_tool_registry()
        registry.print_summary()
    except Exception as e:
        logger.error(f"❌ Failed to load tool registry: {e}")
        raise
    
    # Initialize Orchestrator
    logger.info("\n Initializing Task Orchestration System...")
    try:
        init_orchestrator()
        logger.info("✅ Task Orchestrator initialized")
        
        # Initialize Server Executor
        server_executor = init_server_executor()
        logger.info("✅ Server Tool Executor initialized")

        # 5. Register WebSocket task handlers
        logger.info("📡 Registering WebSocket handlers...")
        # real cleint emmiter ws
        # task_handler = await register_task_events(sio, connected_users)
        #  Add mock client emitter - mimicking task_handler behavior
        mock_emitter = get_task_emitter()

               
        # Initialize Execution Engine
        execution_engine = init_execution_engine()
        logger.info("Execution Engine initialized")
        
        # Wire them together
        execution_engine.set_server_executor(server_executor)
        execution_engine.set_client_emitter(mock_emitter)
        logger.info("Components wired together")
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize orchestration: {e}")
        raise
    
    # Connect to database
    await connect_to_mongo()
    await create_indexes()
    logger.info(" Database connected")
    
    # Initialize WebSocket
    logger.info("📡 WebSocket server available at /ws")
    init_socket_utils(sio, connected_users)
    logger.info(" WebSocket initialized")
    
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