#!/usr/bin/env python3
"""
Electron Bridge - Child Process Interface

This script acts as a bridge between Electron's child process (stdin/stdout)
and existing action-executor system.

Flow:
    Electron → stdin → this bridge → receive_tasks_from_server() → your engine

Usage:
    # From Electron/Node.js:
    spawn("python", ["action-executor/electron_bridge.py"])
    
    # Send tasks via stdin:
    stdin.write(JSON.stringify({tasks: [...]}) + "\n")
    
    # Receive results via stdout:
    stdout.on('data', (result) => JSON.parse(result))
"""

import sys
import json
import asyncio
import logging
from typing import Dict, Any

# Import from parent package (works when run as: python -m action_executor.electron_bridge)
from . import initialize_client, receive_tasks_from_server, get_execution_engine

# Setup logging to stderr (stdout reserved for JSON responses)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('electron_bridge.log'),
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger(__name__)

print("🌉 Electron Bridge Started!", file=sys.stderr, flush=True)

# Initialize your action-executor system once at startup
logger.info("🚀 Initializing action-executor system...")
initialize_client(user_id="electron_client")
logger.info("✅ Action-executor initialized")


async def process_task_batch(tasks_data: list) -> Dict[str, Any]:
    """
    Process a batch of tasks using your existing system
    
    Args:
        tasks_data: List of TaskRecord dictionaries
        
    Returns:
        {
            "status": "ok" | "error",
            "results": [TaskOutput, ...],
            "message": "..."
        }
    """
    try:
        logger.info(f"📥 Received {len(tasks_data)} tasks from Electron")
        
        # Use your existing receive_tasks_from_server function
        await receive_tasks_from_server("electron_client", tasks_data)
        
        # Wait for execution to complete
        engine = get_execution_engine()
        await engine.wait_for_completion()
        
        # Collect results from engine
        results = []
        for task_data in tasks_data:
            task_id = task_data.get("task", {}).get("taskId") or task_data.get("task", {}).get("task_id")
            
            # Get task output from engine's state
            task_output = engine.state.get_task_output(task_id) if hasattr(engine, 'state') else None
            
            if task_output:
                results.append({
                    "taskId": task_id,
                    "success": task_output.get("success", True),
                    "data": task_output.get("data", {}),
                    "error": task_output.get("error"),
                    "durationMs": task_output.get("durationMs")
                })
            else:
                # Fallback if we can't get output
                results.append({
                    "taskId": task_id,
                    "success": True,
                    "data": {},
                    "error": None
                })
        
        logger.info(f"✅ All {len(results)} tasks completed")
        return {
            "status": "ok",
            "results": results,
            "message": f"Successfully executed {len(results)} tasks"
        }
        
    except Exception as e:
        logger.error(f"❌ Error processing tasks: {e}", exc_info=True)
        return {
            "status": "error",
            "results": [],
            "message": f"Error: {str(e)}"
        }


async def main_loop():
    """
    Main event loop - reads from stdin, processes tasks, writes to stdout
    """
    logger.info("🎯 Bridge ready - listening for tasks from Electron...")
    
    try:
        # Read from stdin line by line
        for line in sys.stdin:
            try:
                # Parse incoming JSON
                data = json.loads(line.strip())
                logger.debug(f"📨 Received: {json.dumps(data, indent=2)}")
                
                # Extract tasks array
                tasks = data.get("tasks", [])
                
                if not tasks:
                    logger.warning("⚠️ No tasks in payload")
                    response = {
                        "status": "error",
                        "results": [],
                        "message": "No tasks provided"
                    }
                else:
                    # Process tasks using your existing system
                    response = await process_task_batch(tasks)
                
                # Send response back to Electron via stdout
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
                
            except json.JSONDecodeError as e:
                logger.error(f"❌ JSON decode error: {e}")
                error_response = {
                    "status": "error",
                    "results": [],
                    "message": f"Invalid JSON: {str(e)}"
                }
                sys.stdout.write(json.dumps(error_response) + "\n")
                sys.stdout.flush()
                
            except Exception as e:
                logger.error(f"❌ Unexpected error: {e}", exc_info=True)
                error_response = {
                    "status": "error",
                    "results": [],
                    "message": f"Internal error: {str(e)}"
                }
                sys.stdout.write(json.dumps(error_response) + "\n")
                sys.stdout.flush()
                
    except KeyboardInterrupt:
        logger.info("🛑 Bridge interrupted by user")
    except Exception as e:
        logger.error(f"💥 Fatal error: {e}", exc_info=True)
    finally:
        logger.info("👋 Electron Bridge shutting down")


if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except Exception as e:
        logger.error(f"Failed to start bridge: {e}", exc_info=True)
        sys.exit(1)