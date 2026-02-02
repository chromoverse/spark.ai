# python-service/actions/utils/typing_simulator.py
import logging
import time
from typing import Optional, Any

logger = logging.getLogger(__name__)


class TypingSimulator:
    """Simulates real-time keyboard typing using pyautogui"""
    
    def __init__(self, typing_speed: float = 0.05):
        """
        Args:
            typing_speed: Delay between keystrokes in seconds (default 0.05 = 50ms)
        """
        self.typing_speed = typing_speed
        self.pyautogui = None
        self._init_pyautogui()
    
    def _init_pyautogui(self) -> None:
        """Initialize pyautogui"""
        try:
            import pyautogui
            pyautogui.FAILSAFE = False
            pyautogui.PAUSE = 0
            self.pyautogui = pyautogui
            logger.info("PyAutoGUI initialized for typing")
        except ImportError:
            logger.error("pyautogui not installed")
            self.pyautogui = None
    
    def type_text(self, text: str, delay_before: float = 0.5) -> bool:
        """
        Type text with natural speed
        
        Args:
            text: The text to type
            delay_before: Wait time before starting to type (seconds)
            
        Returns:
            True if successful, False otherwise
        """
        if not self.pyautogui:
            logger.error("pyautogui not available")
            return False
        
        try:
            logger.info(f"Typing {len(text)} characters...")
            time.sleep(delay_before)
            
            # Use write() for actual text typing
            self.pyautogui.write(text, interval=self.typing_speed)
            
            logger.info("Typing completed")
            return True
            
        except Exception as e:
            logger.error(f"Error during typing: {e}", exc_info=True)
            return False