# python-service/actions/app_features/apps/vscode.py
import logging
import tempfile
import os
import time
import subprocess
import platform
from typing import Dict, Any, List
from .base import BaseApp
from ...utils.process_manager import ProcessManager

logger = logging.getLogger(__name__)


class VSCodeApp(BaseApp):
    """Visual Studio Code application handler"""
    
    @property
    def app_name(self) -> str:
        return "VS Code"
    
    @property
    def process_names(self) -> List[str]:
        return ["code.exe", "code", "Code.exe", "Code Helper", "Code - Insiders"]
    
    @property
    def executables(self) -> Dict[str, List[str]]:
        return {
            "windows": ["code.cmd", "code", "Code.exe"],
            "linux": ["code"],
            "darwin": ["code"]  # VS Code CLI is better than .app
        }
    
    @property
    def supports_content(self) -> bool:
        return True
    
    @property
    def supports_typing(self) -> bool:
        return False  # VS Code uses files, not typing
    
    @property
    def wait_timeout(self) -> int:
        return 8  # VS Code needs more time on first launch
    
    def open(self) -> Dict[str, Any]:
        """Open VS Code with optional content file"""
        try:
            executable = self.find_executable()
            if not executable:
                return {
                    "success": False,
                    "app_name": self.app_name,
                    "error": f"{self.app_name} is not installed or 'code' command not in PATH"
                }
            
            # Check if VS Code is already running
            was_running = ProcessManager.is_process_running(self.process_names)
            logger.info(f"VS Code already running: {was_running}")
            
            # If content exists, create temp file and open with VS Code
            if self.content:
                temp_file = self._create_temp_file()
                if not temp_file:
                    return {
                        "success": False,
                        "app_name": self.app_name,
                        "error": "Failed to create temp file"
                    }
                
                # Launch with file using --new-window flag for better reliability
                logger.info(f"Launching VS Code with file: {temp_file}")
                
                try:
                    if platform.system() == "Windows":
                        # Use --new-window to ensure it opens
                        subprocess.Popen([executable, temp_file, "--new-window"], 
                                       shell=False,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
                    else:
                        subprocess.Popen([executable, temp_file, "--new-window"])
                    
                    # Wait longer on first launch
                    wait_time = 3 if was_running else 8
                    logger.info(f"Waiting {wait_time}s for VS Code to open...")
                    
                    if not was_running:
                        # First launch - wait for process to start
                        if ProcessManager.wait_for_process(self.process_names, wait_time):
                            logger.info("VS Code process detected")
                        else:
                            logger.warning("VS Code process not detected, but file was opened")
                    else:
                        # Already running - just give it a moment
                        time.sleep(2)
                    
                    return {
                        "success": True,
                        "app_name": self.app_name,
                        "message": f"Opened {self.app_name} with content",
                        "had_content": True,
                        "temp_file": temp_file,
                        "content_length": len(self.content),
                        "was_already_running": was_running
                    }
                    
                except Exception as e:
                    logger.error(f"Failed to launch VS Code: {e}")
                    return {
                        "success": False,
                        "app_name": self.app_name,
                        "error": f"Failed to launch: {str(e)}"
                    }
            
            # Launch without file
            try:
                logger.info("Launching VS Code without file")
                
                if platform.system() == "Windows":
                    subprocess.Popen([executable, "--new-window"], 
                                   shell=False,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    subprocess.Popen([executable, "--new-window"])
                
                wait_time = 3 if was_running else 8
                
                if not was_running:
                    ProcessManager.wait_for_process(self.process_names, wait_time)
                else:
                    time.sleep(1)
                
                return {
                    "success": True,
                    "app_name": self.app_name,
                    "message": f"Opened {self.app_name}",
                    "had_content": False,
                    "was_already_running": was_running
                }
                
            except Exception as e:
                logger.error(f"Failed to launch VS Code: {e}")
                return {
                    "success": False,
                    "app_name": self.app_name,
                    "error": f"Failed to launch: {str(e)}"
                }
            
        except Exception as e:
            logger.error(f"Error opening {self.app_name}: {e}", exc_info=True)
            return {
                "success": False,
                "app_name": self.app_name,
                "error": str(e)
            }
    
    def _create_temp_file(self) -> str:
        """Create temporary file with content"""
        try:
            # Use .md for better VS Code highlighting
            fd, temp_path = tempfile.mkstemp(suffix=".md", prefix="spark_ai_")
            
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(self.content)
            
            logger.info(f"Created temp file: {temp_path}")
            return temp_path
            
        except Exception as e:
            logger.error(f"Failed to create temp file: {e}")
            return ""