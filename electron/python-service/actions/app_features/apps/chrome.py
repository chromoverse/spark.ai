# python-service/actions/apps/chrome.py
import logging
import webbrowser
from typing import Dict, Any, List
from .base import BaseApp
from ...utils.process_manager import ProcessManager
from ...utils.typing_simulator import TypingSimulator

logger = logging.getLogger(__name__)


class ChromeApp(BaseApp):
    """Google Chrome application handler"""
    
    @property
    def app_name(self) -> str:
        return "Chrome"
    
    @property
    def process_names(self) -> List[str]:
        return ["chrome.exe", "google-chrome", "Google Chrome"]
    
    @property
    def executables(self) -> Dict[str, List[str]]:
        return {
            "windows": ["chrome.exe", r"C:\Program Files\Google\Chrome\Application\chrome.exe"],
            "linux": ["google-chrome", "google-chrome-stable"],
            "darwin": ["Google Chrome.app"]
        }
    
    @property
    def wait_timeout(self) -> int:
        return 3
    
    def open(self) -> Dict[str, Any]:
        """Open Chrome browser"""
        try:
            was_running = ProcessManager.is_process_running(self.process_names)
            
            if was_running:
                logger.info(f"{self.app_name} already running, focusing...")
                ProcessManager.focus_window(self.process_names)
                return {
                    "success": True,
                    "app_name": self.app_name,
                    "message": f"Focused existing {self.app_name} window",
                    "was_already_running": True
                }
            
            # Try to launch using executable
            executable = self.find_executable()
            if executable:
                if self.launch_app(executable):
                    ProcessManager.wait_for_process(self.process_names, self.wait_timeout)
                    return {
                        "success": True,
                        "app_name": self.app_name,
                        "message": f"Opened {self.app_name}"
                    }
            
            # Fallback: use webbrowser module
            webbrowser.open("https://google.com")
            
            return {
                "success": True,
                "app_name": self.app_name,
                "message": f"Opened {self.app_name} (via webbrowser)"
            }
            
        except Exception as e:
            logger.error(f"Error opening {self.app_name}: {e}", exc_info=True)
            return {
                "success": False,
                "app_name": self.app_name,
                "error": str(e)
            }