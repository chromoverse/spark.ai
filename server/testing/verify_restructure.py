
import sys
import os
import asyncio
import logging

# Add project root to path
sys.path.append(os.path.abspath("d:/siddhant-files/projects/ai_assistant/ai_local/server"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("verification")

async def verify():
    logger.info("🔍 Starting Verification...")
    
    try:
        # 1. Check Imports
        logger.info("1. Checking Imports...")
        import app.kernel.execution.orchestrator
        import app.agent.desktop_notifications
        import app.plugins.tools.registry_loader
        import app.plugins.tools.tool_instance_loader
        import app.main
        logger.info("✅ Imports successful")
        
        # 2. Check Registry Loading
        logger.info("2. Checking Registry Loading...")
        from app.plugins.tools.registry_loader import load_tool_registry, get_tool_registry
        load_tool_registry()
        registry = get_tool_registry()
        logger.info(f"✅ Registry loaded: {len(registry.tools)} tools")
        
        # 3. Check Task Emitter Initialization
        logger.info("3. Checking Task Emitter...")
        from app.kernel.execution.task_emitter import init_task_emitter, get_task_emitter
        init_task_emitter() # Reset
        emitter = get_task_emitter()
        
        # Test env setting
        emitter.set_environment("desktop")
        assert emitter.environment == "desktop"
        
        emitter.set_environment("production")
        assert emitter.environment == "production"
        logger.info("✅ Task Emitter initialized and env-aware")
        
        # 4. Check Startup Registrations
        logger.info("4. Checking Startup Registrations...")
        import app.startup_registrations
        import app.auto_initializer
        
        # Access private _registry (list of tuples)
        registered_names = [name for name, _ in app.auto_initializer._registry]
        
        logger.info(f"   Registered initializers: {registered_names}")
        assert "Agentic System (Orchestrator + Tools)" in registered_names
        logger.info("✅ Agentic System registered")
        
        logger.info("\n🎉 VERIFICATION SUCCESSFUL!")
        
    except Exception as e:
        logger.error(f"❌ Verification Failed: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(verify())

