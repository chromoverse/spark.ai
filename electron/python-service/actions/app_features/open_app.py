# python-service/actions/open_app.py
import logging
from typing import Dict, Any, List, Optional
from difflib import get_close_matches

# Import all app handlers
from .apps.notepad import NotepadApp
from .apps.vscode import VSCodeApp
from .apps.chrome import ChromeApp
from .apps.whatsapp import WhatsAppApp
from .apps.base import BaseApp

logger = logging.getLogger(__name__)

# App registry with aliases for fuzzy matching
APP_REGISTRY = {
    "notepad": {
        "class": NotepadApp,
        "aliases": ["notepad", "text editor", "notes", "text"]
    },
    "vscode": {
        "class": VSCodeApp,
        "aliases": ["vscode", "vs code", "visual studio code", "code editor", "coding", "code"]
    },
    "chrome": {
        "class": ChromeApp,
        "aliases": ["chrome", "google chrome", "browser", "web browser"]
    },
    "whatsapp": {
        "class": WhatsAppApp,
        "aliases": ["whatsapp", "whats app", "wa"]
    }
}


def find_app_match(app_name: str) -> Optional[str]:
    """
    Find the best matching app using fuzzy matching on aliases
    
    Args:
        app_name: The app name to match
        
    Returns:
        Matched app key or None
    """
    app_name_lower = app_name.lower().strip()
    
    # Direct match
    if app_name_lower in APP_REGISTRY:
        return app_name_lower
    
    # Check aliases
    for app_key, app_info in APP_REGISTRY.items():
        if app_name_lower in [alias.lower() for alias in app_info.get("aliases", [])]:
            return app_key
    
    # Fuzzy matching on all aliases
    all_aliases = []
    alias_to_app = {}
    
    for app_key, app_info in APP_REGISTRY.items():
        for alias in app_info.get("aliases", []):
            all_aliases.append(alias.lower())
            alias_to_app[alias.lower()] = app_key
    
    matches = get_close_matches(app_name_lower, all_aliases, n=1, cutoff=0.6)
    
    if matches:
        return alias_to_app[matches[0]]
    
    return None


def open_single_app(app_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Open a single application using the appropriate app handler
    
    Args:
        app_name: Name of the app to open
        payload: Full IAiResponsePayload
        
    Returns:
        Result dictionary with success status and details
    """
    logger.info(f"Attempting to open: {app_name}")
    
    # Find matching app
    matched_app = find_app_match(app_name)
    
    if not matched_app:
        logger.warning(f"No match found for: {app_name}")
        available_apps = list(APP_REGISTRY.keys())
        return {
            "success": False,
            "app_name": app_name,
            "error": f"Could not find an app matching '{app_name}'",
            "suggestion": f"Try: {', '.join(available_apps)}"
        }
    
    # Get app class
    app_info = APP_REGISTRY[matched_app]
    app_class = app_info["class"]
    
    try:
        # Instantiate app handler with full payload
        app_handler: BaseApp = app_class(payload)
        
        logger.info(f"Matched '{app_name}' to '{matched_app}', using {app_class.__name__}")
        
        # Open the app
        result = app_handler.open()
        
        # Add matched app info to result
        result["requested_name"] = app_name
        result["matched_as"] = matched_app
        
        return result
        
    except Exception as e:
        logger.error(f"Error instantiating or opening {matched_app}: {e}", exc_info=True)
        return {
            "success": False,
            "app_name": app_name,
            "matched_as": matched_app,
            "error": f"Failed to open {matched_app}: {str(e)}"
        }


def open_app(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle opening applications with support for multiple platforms
    Receives the full IAiResponsePayload from main_service
    
    Args:
        payload: Full IAiResponsePayload containing actionDetails and answerDetails
        
    Returns:
        Result dictionary with action status and details
    """
    try:
        # Extract actionDetails
        action_details = payload.get("actionDetails", {})
        answer_details = payload.get("answerDetails", {})
        
        app_name = action_details.get("app_name", "").strip()
        platforms = action_details.get("platforms", [])
        
        logger.info(f"open_app called with app_name: '{app_name}', platforms: {platforms}")
        
        if answer_details.get("content"):
            logger.info(f"Has answer content: {len(answer_details.get('content'))} characters")
        
        if not app_name and not platforms:
            return {
                "action": "open_app",
                "success": False,
                "error": "No app_name or platforms provided"
            }
        
        results = []
        
        # If platforms specified, open multiple apps
        if platforms:
            logger.info(f"Opening multiple platforms: {platforms}")
            for platform_name in platforms:
                result = open_single_app(platform_name, payload)
                results.append(result)
        else:
            # Open single app
            result = open_single_app(app_name, payload)
            results.append(result)
        
        # Determine overall success
        successful_apps = [r for r in results if r.get("success")]
        failed_apps = [r for r in results if not r.get("success")]
        
        response = {
            "action": "open_app",
            "total_attempts": len(results),
            "successful": len(successful_apps),
            "failed": len(failed_apps),
            "results": results
        }
        
        # Add summary message
        if successful_apps and not failed_apps:
            app_names = [r.get("app_name", "unknown") for r in successful_apps]
            response["message"] = f"Successfully opened: {', '.join(app_names)}"
            response["success"] = True
        elif successful_apps and failed_apps:
            response["message"] = f"Opened {len(successful_apps)} apps, {len(failed_apps)} failed"
            response["success"] = True
        else:
            response["message"] = "Failed to open any applications"
            response["success"] = False
            response["errors"] = [r.get("error") for r in failed_apps]
        
        return response
        
    except Exception as e:
        logger.error(f"Error in open_app: {e}", exc_info=True)
        return {
            "action": "open_app",
            "success": False,
            "error": str(e)
        }