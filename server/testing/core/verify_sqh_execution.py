from app.cache import RedisManager 
import asyncio
import json
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    """
    Test script using the chat service (recommended approach)
    
    The chat service now handles execution waiting internally
    based on the wait_for_execution parameter
    """
    
    config = RedisManager()
    
    # Connect to database
    from app.db.mongo import connect_to_mongo
    await connect_to_mongo()
    
    # Import after DB connection
    from app.services.chat_service import chat
    from app.core.orchestrator import get_orchestrator
    
    logger.info("\n" + "="*70)
    logger.info("🚀 STARTING CHAT TEST")
    logger.info("="*70 + "\n")
    
    # ========================================================================
    # RECOMMENDED: Use chat service with wait_for_execution=True
    # ========================================================================
    logger.info("\n📋 Testing chat service with execution waiting\n")
    
    response = await chat(
        query="open camera ",
        user_id="guest",
        wait_for_execution=True,    # ✅ Wait for tasks to complete
        execution_timeout=30.0       # ✅ Max 30 seconds
    )
    
    logger.info(f"💬 AI Response: {response.cognitive_state.answer_english}")
    logger.info(f"🔧 Tools Requested: {response.requested_tool}")
    logger.info("✅ Chat completed (with execution)!\n")
    
    
    # ========================================================================
    # APPROACH 2: Use completion event (MOST ROBUST - with timeout)
    # ========================================================================
    # Uncomment to test this approach:
    """
    logger.info("\n📋 Approach 2: Use completion event with timeout\n")
    
    execution_task = await process_sqh()
    
    # Wait with timeout using built-in method
    engine = get_execution_engine()
    success = await engine.wait_for_completion("guest", timeout=30)
    
    if success:
        logger.info("✅ Execution completed successfully!\n")
    else:
        logger.warning("⏰ Execution timed out or failed!\n")
    """




if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n🛑 Interrupted by user")
    except Exception as e:
        logger.error(f"\n❌ Fatal error: {e}", exc_info=True)