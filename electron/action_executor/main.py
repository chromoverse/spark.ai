# action-executor/main.py
"""
Action Executor - Main Entry Point

Standalone client-side execution system.
All imports are relative - can be copied to Electron.

Usage:
    from action_executor import initialize_client, receive_tasks_from_server
    
    # Initialize (idempotent)
    initialize_client()=
    
    # Receive tasks from server
    await receive_tasks_from_server(user_id, task_records)
    
    # Or run demo directly:
    python -m action_executor.main
"""

import asyncio
import logging
import sys
from typing import List, Dict, Any, Union

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


# Global instances
_initialized = False
_execution_engine = None


def initialize_client(user_id: str = "default_client") -> None:
    """
    Initialize all client components.
    
    Idempotent - can be called multiple times.
    """
    global _initialized, _execution_engine
    
    if _initialized and _execution_engine:
        logger.info("⚠️ Client already initialized, skipping...")
        return
    
    logger.info("\n" + "="*70)
    logger.info("🚀 INITIALIZING CLIENT CORE")
    logger.info("="*70 + "\n")
    
    try:
        # 1. Load all client tools (creates instances, injects schemas)
        from .tools.loader import load_client_tools
        load_client_tools()
        
        # 2. Initialize execution engine
        from .engine import init_client_engine
        _execution_engine = init_client_engine(user_id=user_id)
        
        # 3. Initialize and set tool executor
        from .executor import init_client_executor
        tool_executor = init_client_executor()
        _execution_engine.set_tool_executor(tool_executor)
        
        _initialized = True
        
        logger.info("\n" + "="*70)
        logger.info("✅ CLIENT CORE INITIALIZED")
        logger.info("="*70 + "\n")
        
    except Exception as e:
        logger.error(f"❌ Initialization failed: {e}", exc_info=True)
        raise


def get_execution_engine(auto_init: bool = True):
    """Get the client execution engine (initializes if needed)."""
    if not _initialized and auto_init:
        initialize_client()
    
    if not _execution_engine:
        raise RuntimeError("Client Core not initialized")
        
    return _execution_engine


async def receive_tasks_from_server(
    user_id: str, 
    task_input: Union[List[Dict[str, Any]], Dict[str, Any]]
) -> None:
    """
    Public API: Receive tasks from server.
    
    This function is designed to be the callback/handler for WebSocket messages.
    Host process (Electron/Python) should call this when 'task' events arrive.
    
    Args:
        user_id: User ID
        task_input: List of tasks OR single task dict
    """
    # 1. Auto-init checks
    if not _initialized:
        logger.info("⚠️ Client Core not initialized, initializing now...")
        initialize_client(user_id)
    
    engine = get_execution_engine()
    
    # 2. Update engine user_id if changed (for multi-user support potentially)
    if engine.user_id != user_id:
        engine.user_id = user_id
    
    # 3. Normalize input to list
    tasks_to_process = []
    if isinstance(task_input, list):
        tasks_to_process = task_input
    elif isinstance(task_input, dict):
        tasks_to_process = [task_input]
    else:
        logger.error(f"❌ Invalid task input format: {type(task_input)}")
        return

    if not tasks_to_process:
        logger.warning("⚠️ No tasks to process")
        return

    logger.info(f"\n📨 [CLIENT API] Received {len(tasks_to_process)} task(s)")
    for i, task_dict in enumerate(tasks_to_process, 1):
        task_info = task_dict.get("task", {})
        logger.info(f"   {i}. {task_info.get('task_id')}: {task_info.get('tool')}")
    
    # 4. Pass to engine
    await engine.receive_tasks(tasks_to_process)
    
    # 5. ✅ KEY FIX: Start processing loop if not already running
    logger.info("🔄 [CLIENT API] Starting/ensuring execution loop is running...")
    
    # Check if engine has a method to start/ensure loop is running
    # Assuming your engine has a `process_tasks()` or similar method
    # If not, we need to trigger it here
    
    if hasattr(engine, 'start'):
        asyncio.create_task(engine.start())
    else:
        # Fallback: trigger processing manually
        logger.warning("⚠️ Engine doesn't have a start method, tasks may not execute")


async def run_demo_tasks() -> None:
    """
    Run demo with sample tasks.
    """
    logger.info("Starting Demo Mode...")
    
    # Sample chain: create folder -> create file
    sample_tasks = [
        {
            "task": {
                "task_id": "open_app",
                "tool": "folder_create",
                "execution_target": "client",
                "depends_on": [],
                "inputs": {
                    "target": "camera"
                },
                "lifecycle_messages": {
                    "on_start": "Creating folder...",
                    "on_success": "Folder created!"
                }
            },
            "status": "pending"
        },
        {
            "task": {
                "task_id": "demo_file",
                "tool": "file_create",
                "execution_target": "client",
                "depends_on": ["demo_folder"],
                "inputs": {
                    "path": "~/client_core_demo/test_folder/demo.txt",
                    "content": "This file was created by the Client Core demo!"
                },
                "lifecycle_messages": {
                    "on_start": "Creating file...",
                    "on_success": "File created!"
                }
            },
            "status": "pending"
        }
    ]
    
    await receive_tasks_from_server("demo_user", sample_tasks)
    
    # Keep alive to allow execution completion
    engine = get_execution_engine()
    await engine.wait_for_completion()


def main():
    """Main entry point."""
    try:
        asyncio.run(run_demo_tasks())
    except KeyboardInterrupt:
        logger.info("Stopped by user")


if __name__ == "__main__":
    main()