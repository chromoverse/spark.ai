# python-service/actions/navigate.py
import logging
from typing import Dict, Any
import webbrowser

logger = logging.getLogger(__name__)

def navigate(action_details: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle navigation to URLs
    """
    try:
        location = action_details.get("location", "")
        
        logger.info(f"Navigating to: {location}")
        
        webbrowser.open(location)
        
        return {
            "action": "navigate",
            "location": location,
            "message": f"Opened {location}"
        }
        
    except Exception as e:
        logger.error(f"Error navigating: {e}")
        raise