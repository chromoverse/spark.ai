# python-service/actions/app_features/apps/notepad.py
import logging
import subprocess
import time
import platform
import os
from typing import Dict, Any, List, Optional
from .base import BaseApp
from ...utils.process_manager import ProcessManager

logger = logging.getLogger(__name__)


class NotepadApp(BaseApp):
    """Notepad application handler with real-time typing support"""
    
    @property
    def app_name(self) -> str:
        return "Notepad"
    
    @property
    def process_names(self) -> List[str]:
        return ["notepad.exe", "gedit", "kate"]
    
    @property
    def executables(self) -> Dict[str, List[str]]:
        return {
            "windows": ["notepad.exe"],
            "linux": ["gedit", "kate", "nano"],
            "darwin": ["TextEdit.app"]
        }
    
    @property
    def supports_content(self) -> bool:
        return True
    
    @property
    def supports_typing(self) -> bool:
        return True
    
    @property
    def wait_timeout(self) -> int:
        return 3
    
    def open(self) -> Dict[str, Any]:
        """Open Notepad with optional content"""
        try:
            # If we have content, use the temp file method (more reliable)
            if self.content:
                return self._open_with_typing()
            
            # No content - just open notepad
            executable = self.find_executable()
            if not executable:
                return {
                    "success": False,
                    "app_name": self.app_name,
                    "error": f"{self.app_name} is not installed on your system"
                }
            
            self.launch_app(executable)
            ProcessManager.wait_for_process(self.process_names, self.wait_timeout)
            
            return {
                "success": True,
                "app_name": self.app_name,
                "message": f"Opened {self.app_name}",
                "had_content": False
            }
            
        except Exception as e:
            logger.error(f"Error opening {self.app_name}: {e}", exc_info=True)
            return {
                "success": False,
                "app_name": self.app_name,
                "error": str(e)
            }
    
    def _open_with_temp_file(self) -> Dict[str, Any]:
        """
        Open Notepad with content using a temp file
        More reliable than typing simulation
        """
        try:
            import tempfile
            
            logger.info("Creating temp file with content...")
            
            # Create temp file
            fd, temp_path = tempfile.mkstemp(suffix=".txt", prefix="spark_ai_")
            
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(self.content)
            
            logger.info(f"Temp file created: {temp_path}")
            
            # Open notepad with the file
            if platform.system() == "Windows":
                subprocess.Popen(["notepad.exe", temp_path])
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", "-a", "TextEdit", temp_path])
            else:
                subprocess.Popen(["gedit", temp_path])
            
            # Wait for process
            ProcessManager.wait_for_process(self.process_names, self.wait_timeout)
            
            return {
                "success": True,
                "app_name": self.app_name,
                "message": f"Opened {self.app_name} with content",
                "had_content": True,
                "content_length": len(self.content),
                "temp_file": temp_path,
                "method": "temp-file"
            }
            
        except Exception as e:
            logger.error(f"Error opening with temp file: {e}", exc_info=True)
            return {
                "success": False,
                "app_name": self.app_name,
                "error": f"Failed to open with content: {str(e)}"
            }
    
    def _open_with_typing(self) -> Dict[str, Any]:
        """
        Alternative: Open Notepad and type content with pyautogui
        Use this only if you specifically want typing animation
        """
        try:
            # Launch notepad first
            if platform.system() == "Windows":
                subprocess.Popen(["notepad.exe"])
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", "-a", "TextEdit"])
            else:
                subprocess.Popen(["gedit"])
            
            logger.info("Waiting for Notepad to open...")
            
            # Wait for process to start
            if not ProcessManager.wait_for_process(self.process_names, self.wait_timeout):
                return {
                    "success": False,
                    "app_name": self.app_name,
                    "error": "Notepad did not start in time"
                }
            
            # Extra wait for window to be fully ready
            time.sleep(1.5)
            
            # Now type with pyautogui
            logger.info("Starting typing simulation...")
            
            try:
                import pyautogui
                
                # Ensure notepad is focused (click in center of screen)
                import win32gui
                hwnd = win32gui.FindWindow(None, "SparkAI - Notepad")
                if hwnd:
                    win32gui.SetForegroundWindow(hwnd)
                    time.sleep(0.3)
                
                # Type slowly and reliably
                for char in self.content:
                    pyautogui.press(char) if len(char) == 1 and char.isalnum() else pyautogui.typewrite([char])
                    time.sleep(0.01)
                
                logger.info("Typing completed")
                
                return {
                    "success": True,
                    "app_name": self.app_name,
                    "message": f"Opened {self.app_name} and typed content",
                    "had_content": True,
                    "content_length": len(self.content),
                    "method": "typing-simulation"
                }
                
            except Exception as e:
                logger.error(f"Typing failed: {e}")
                return {
                    "success": False,
                    "app_name": self.app_name,
                    "error": f"Typing failed: {str(e)}"
                }
                
        except Exception as e:
            logger.error(f"Error in typing method: {e}", exc_info=True)
            return {
                "success": False,
                "app_name": self.app_name,
                "error": str(e)
            }