# python-service/actions/app_features/apps/whatsapp.py
import logging
import subprocess,time
import platform
import os
from typing import Dict, Any, List
from .base import BaseApp
from ...utils.process_manager import ProcessManager
from ...utils.whatsapp_ui import WhatsAppUISender

logger = logging.getLogger(__name__)


class WhatsAppApp(BaseApp):
    """WhatsApp application handler"""
    
    @property
    def app_name(self) -> str:
        return "WhatsApp"
    
    @property
    def process_names(self) -> List[str]:
        return ["WhatsApp.exe", "whatsapp"]
    
    @property
    def executables(self) -> Dict[str, List[str]]:
        # Windows has multiple possible locations
        return {
            "windows": [
                "WhatsApp.exe",
                # Microsoft Store version
                os.path.expandvars(r"%LOCALAPPDATA%\WhatsApp\WhatsApp.exe"),
                os.path.expandvars(r"%PROGRAMFILES%\WindowsApps\WhatsApp\WhatsApp.exe"),
                # Desktop app version
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\WhatsApp\WhatsApp.exe"),
            ],
            "linux": ["whatsapp", "whatsapp-desktop"],
            "darwin": ["WhatsApp.app"]
        }
    
    @property
    def wait_timeout(self) -> int:
        return 5
    
    def open(self) -> Dict[str, Any]:
        """Open WhatsApp"""
        try:
            # Check if already running
            was_running = ProcessManager.is_process_running(self.process_names)
            
            if was_running:
                logger.info(f"{self.app_name} already running, focusing...")
                ProcessManager.focus_window(self.process_names)
                time.sleep(0.5)
                return {
                    "success": True,
                    "app_name": self.app_name,
                    "message": f"Focused existing {self.app_name} window",
                    "was_already_running": True
                }
            
            # Try to find and launch executable
            executable = self.find_executable()
            
            # if executable:
            #     logger.info(f"Found WhatsApp at: {executable}")
                
            #     if self.launch_app(executable):
            #         # Wait for process to start
            #         if ProcessManager.wait_for_process(self.process_names, self.wait_timeout):
            #             return {
            #                 "success": True,
            #                 "app_name": self.app_name,
            #                 "message": f"Opened {self.app_name}",
            #                 "executable": executable
            #             }
            #         else:
            #             return {
            #                 "success": False,
            #                 "app_name": self.app_name,
            #                 "error": f"{self.app_name} launched but process not detected",
            #                 "executable": executable
            #             }
            
            # # Fallback: Try Windows Store app launch
            # if platform.system() == "Windows":
            #     logger.info("Trying Windows Store WhatsApp launch...")
            #     return self._launch_windows_store_app()
            
            # Fallback: Open WhatsApp Web
            logger.warning("WhatsApp desktop not found, opening WhatsApp Web...")
            return self._open_whatsapp_web()
            
        except Exception as e:
            logger.error(f"Error opening {self.app_name}: {e}", exc_info=True)
            return {
                "success": False,
                "app_name": self.app_name,
                "error": str(e)
            }
    
    def _launch_windows_store_app(self) -> Dict[str, Any]:
        """Launch WhatsApp from Windows Store using shell:AppsFolder"""
        try:
            import subprocess
            
            # Try to launch using the Windows Store app protocol
            # This works for apps installed from Microsoft Store
            cmd = 'explorer.exe shell:AppsFolder\\5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App'
            
            subprocess.Popen(cmd, shell=True)
            
            logger.info("Launched WhatsApp via Windows Store protocol")
            
            # Wait a bit longer for Store apps
            import time
            time.sleep(2)
            
            if ProcessManager.wait_for_process(self.process_names, timeout=8):
                return {
                    "success": True,
                    "app_name": self.app_name,
                    "message": f"Opened {self.app_name} (Windows Store)",
                    "method": "windows-store"
                }
            else:
                # Launched but couldn't verify - still return success
                return {
                    "success": True,
                    "app_name": self.app_name,
                    "message": f"Launched {self.app_name} (verification pending)",
                    "method": "windows-store"
                }
                
        except Exception as e:
            logger.error(f"Windows Store launch failed: {e}")
            return {
                "success": False,
                "app_name": self.app_name,
                "error": f"Windows Store launch failed: {str(e)}"
            }
    
    def _open_whatsapp_web(self) -> Dict[str, Any]:
        """Fallback: Open WhatsApp Web in browser"""
        try:
           
            # import webbrowser
            # webbrowser.open("https://web.whatsapp.com")

            # if(self.payload.get("number")):
            WhatsAppUISender.send("9824870400","Hello bhai")
            
            return {
                "success": True,
                "app_name": "WhatsApp Web",
                "message": "Opened WhatsApp Web in browser (desktop app not found)",
                "method": "web-fallback"
            }
        except Exception as e:
            return {
                "success": False,
                "app_name": self.app_name,
                "error": f"Could not open WhatsApp: {str(e)}"
            }