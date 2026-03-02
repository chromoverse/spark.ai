"""
Startup initializer registrations.

Registers all module-level warm-up / init functions with the
``auto_initializer`` registry.  Importing this module is enough —
``main.py`` just does::

    import app.startup_registrations          # registers everything
    from app.auto_initializer import run_all  # then runs them
    await run_all()
"""

from app.auto_initializer import register


# ── 1. API Key cache (sync — reads Windows registry once) ──
def _warmup_key_cache() -> None:
    from app.ai.providers.key_manager import _KeyCache
    _KeyCache.get_all()


register("KeyCache (API keys)", _warmup_key_cache)


# ── 2. Cache client (LocalKV / LanceDB / Redis) ──
async def _warmup_cache_client() -> None:
    from app.cache import cache_manager
    await cache_manager._ensure_client()


register("Cache client (LocalKV/Redis)", _warmup_cache_client)


# ── 3. TTS engine (Kokoro) ──
async def _warmup_tts() -> None:
    from app.services.tts_services import tts_service
    await tts_service.warmup_tts_engine()


register("TTS engine (Kokoro)", _warmup_tts)


# ── 4. Agentic System (Orchestrator, Engine, Tools) ──
async def _init_agent_system() -> None:
    from app.config import settings  # Module-level singleton (already validated)
    
    environment = settings.environment
    print(f"🌍 Agent System Environment: {environment}")
    
    # ── Step 1: Load Tool Registry (Shared) ──
    from app.agent.shared.registry.loader import load_tool_registry
    load_tool_registry()
    
    # ── Step 2: Load Tool Instances (Server + Client) ──
    from app.agent.shared.tools.loader import load_all_tools
    load_all_tools()
    
    # ── Step 3: Initialize Orchestrator ──
    from app.agent.core.orchestrator import init_orchestrator
    init_orchestrator()
    
    # ── Step 4: Initialize Task Emitter FIRST (engine depends on it) ──
    from app.agent.core.task_emitter import init_task_emitter
    emitter = init_task_emitter()
    emitter.set_environment(environment)
    
    # Wire Socket Handler for production/non-desktop modes
    if environment != "desktop":
        try:
            from app.socket import sio, connected_users
            from app.socket.task_handler import register_task_events
            task_handler = await register_task_events(sio, connected_users)
            emitter.set_socket_handler(task_handler)
            print(f"🔌 Socket Task Handler wired ({environment} mode)")
        except Exception as e:
            print(f"❌ Failed to wire socket handler: {e}")
    
    # ── Step 5: Initialize Execution Engine ──
    from app.agent.core.execution_engine import init_execution_engine
    engine = init_execution_engine()
    
    # ── Step 6: Initialize Server Executor ──
    from app.agent.core.server_executor import init_server_executor
    server_executor = init_server_executor()
    
    # ── Step 7: WIRE EVERYTHING TOGETHER ──
    engine.set_server_executor(server_executor)
    engine.set_client_emitter(emitter)
    
    print(f"✅ Agent System ready (env={environment}, emitter={emitter.environment})")


register("Agentic System (Orchestrator + Tools)", _init_agent_system)
