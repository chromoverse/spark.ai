# python-service/actions/apps/base.py
import logging
import subprocess
import platform
import os
import shutil
from typing import Dict, Any, List, Optional
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BaseApp(ABC):
    """Base class for all application handlers"""
    
    def __init__(self, payload: Dict[str, Any]):
        """
        Initialize the app handler with full payload
        
        Args:
            payload: Full IAiResponsePayload from Electron
        """
        self.payload = payload
        self.action_details = payload.get("actionDetails", {})
        self.answer_details = payload.get("answerDetails", {})
        self.query = self.action_details.get("query", "")
        self.content = self.answer_details.get("content", "").strip()
    
    @property
    @abstractmethod
    def app_name(self) -> str:
        """Official app name for logging"""
        pass
    
    @property
    @abstractmethod
    def process_names(self) -> List[str]:
        """List of process names to check for this app"""
        pass
    
    @property
    @abstractmethod
    def executables(self) -> Dict[str, List[str]]:
        """
        Platform-specific executable paths
        Returns: {"windows": [...], "linux": [...], "darwin": [...]}
        """
        pass
    
    @property
    def supports_content(self) -> bool:
        """Whether this app supports opening with content"""
        return False
    
    @property
    def supports_typing(self) -> bool:
        """Whether this app supports real-time typing simulation"""
        return False
    
    @property
    def wait_timeout(self) -> int:
        """How long to wait for the app to start (seconds)"""
        return 5
    
    def get_platform_key(self) -> str:
        """Get current platform key"""
        system = platform.system().lower()
        if system == "windows":
            return "windows"
        elif system == "darwin":
            return "darwin"
        else:
            return "linux"
    
    def find_executable(self) -> Optional[str]:
        """Find the executable for current platform"""
        platform_key = self.get_platform_key()
        app_paths = self.executables.get(platform_key, [])
        
        for app_path in app_paths:
            if os.path.isfile(app_path):
                return app_path
            
            if shutil.which(app_path):
                return app_path
            
            if app_path.endswith(".app"):
                return app_path
        
        return None
    
    def launch_app(self, executable: str, args: List[str] = []) -> bool:
        """
        Launch the application
        
        Args:
            executable: Path to executable
            args: Additional arguments (e.g., file path)
            
        Returns:
            True if launched successfully
        """
        try:
            cmd = [executable]
            if args:
                cmd.extend(args)
            
            logger.info(f"Launching: {' '.join(cmd)}")
            
            system = platform.system()
            
            if system == "Windows":
                subprocess.Popen(cmd, shell=True)
            elif system == "Darwin":  # macOS
                if executable.endswith(".app"):
                    mac_cmd = ["open", "-a", executable]
                    if args:
                        mac_cmd.extend(args)
                    subprocess.Popen(mac_cmd)
                else:
                    subprocess.Popen(cmd)
            else:  # Linux
                subprocess.Popen(cmd)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to launch {self.app_name}: {e}")
            return False
    
    @abstractmethod
    def open(self) -> Dict[str, Any]:
        """
        Open the application (must be implemented by subclasses)
        
        Returns:
            Result dictionary with success status and details
        """
        pass