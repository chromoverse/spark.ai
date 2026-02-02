# python-service/main_service.py
import sys
import json
import logging
from typing import Dict, Any
from actions.song_features.play_song import play_song
from actions.call_features.make_call import make_call
from actions.send_features.send_message import send_message
from actions.search_features.search import search
from actions.app_features.open_app import open_app
from actions.navigate_features.navigate import navigate
from actions.task_features.create_task import create_task

print("Python service started!", file=sys.stderr, flush=True)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('python_service.log'),
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger(__name__)

# Action handler mapping
ACTION_HANDLERS = {
    "play_song": play_song,
    "make_call": make_call,
    "send_message": send_message,
    "search": search,
    "open_app": open_app,
    "navigate": navigate,
    "create_task": create_task,
    "empty": lambda x: {"status": "ok", "message": "No action needed"}
}

def handle_action(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main action handler that routes to specific action functions
    Receives the full IAiResponsePayload
    """
    try:
        action_details = payload.get("actionDetails", {})
        action_type = action_details.get("type", "empty")
        
        logger.info(f"Handling action: {action_type}")
        logger.debug(f"Full payload: {json.dumps(payload, indent=2)}")
        
        # Get the appropriate handler
        handler = ACTION_HANDLERS.get(action_type)
        
        if not handler:
            return {
                "status": "error",
                "message": f"Unknown action type: {action_type}"
            }
        
        # Execute the handler - pass the WHOLE payload
        result = handler(payload)
        
        # Check if the action itself failed
        if isinstance(result, dict) and result.get("success") is False:
            logger.warning(f"Action {action_type} completed but reported failure")
            return {
                "status": "error",
                "result": result,
                "message": result.get("error", "Action failed")
            }
        
        logger.info(f"Action {action_type} completed successfully")
        return {
            "status": "ok",
            "result": result
        }
        
    except Exception as e:
        logger.error(f"Error handling action: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "message": str(e)
        }

def main():
    """
    Main service loop - reads from stdin, processes actions, writes to stdout
    """
    logger.info("Python service started")
    logger.info("Waiting for commands from Electron...")
    
    try:
        for line in sys.stdin:
            try:
                # Parse incoming JSON
                data = json.loads(line.strip())
                logger.debug(f"Received data: {data}")
                
                # Handle the action
                response = handle_action(data)
                
                # Send response back to Electron
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
                
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error: {e}")
                error_response = {
                    "status": "error",
                    "message": f"Invalid JSON: {str(e)}"
                }
                sys.stdout.write(json.dumps(error_response) + "\n")
                sys.stdout.flush()
                
            except Exception as e:
                logger.error(f"Unexpected error: {e}", exc_info=True)
                error_response = {
                    "status": "error",
                    "message": f"Internal error: {str(e)}"
                }
                sys.stdout.write(json.dumps(error_response) + "\n")
                sys.stdout.flush()
                
    except KeyboardInterrupt:
        logger.info("Service interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
    finally:
        logger.info("Python service shutting down")

if __name__ == "__main__":
    main()