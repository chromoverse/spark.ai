import webbrowser
import time
import urllib.parse
import pyautogui
import platform

from .process_manager import ProcessManager


class WhatsAppUISender:
    """
    WhatsApp Web sender using ProcessManager + real typing
    """

    # Browser process names to detect
    BROWSER_PROCESSES = [
        "chrome.exe", "msedge.exe", "firefox.exe",
        "brave.exe", "opera.exe", "chromium.exe"
    ]

    @staticmethod
    def _is_whatsapp_web_open():
        """
        Check if WhatsApp Web is already open by looking at window titles
        """
        try:
            if platform.system() == "Windows":
                import win32gui
                
                def check_window(hwnd, windows):
                    if win32gui.IsWindowVisible(hwnd):
                        title = win32gui.GetWindowText(hwnd).lower()
                        if "whatsapp" in title:
                            windows.append(hwnd)
                    return True
                
                windows = []
                win32gui.EnumWindows(check_window, windows)
                return len(windows) > 0
        except:
            pass
        return False

    @staticmethod
    def _open_or_focus_browser():
        """
        Focus browser if already running with WhatsApp Web, else open it
        """
        browser_running = ProcessManager.is_process_running(WhatsAppUISender.BROWSER_PROCESSES)
        whatsapp_open = WhatsAppUISender._is_whatsapp_web_open()
        
        if browser_running and whatsapp_open:
            print("[WHATSAPP] WhatsApp Web already open, focusing window...")
            ProcessManager.focus_window(WhatsAppUISender.BROWSER_PROCESSES)
            time.sleep(0.5)
            return True
        
        if browser_running and not whatsapp_open:
            print("[WHATSAPP] Browser running but WhatsApp Web not open, launching...")
            ProcessManager.focus_window(WhatsAppUISender.BROWSER_PROCESSES)
            time.sleep(0.5)
            # Open in current browser window
            webbrowser.open("https://web.whatsapp.com")
            time.sleep(3)
            return True
        
        print("[WHATSAPP] No browser found, launching WhatsApp Web...")
        webbrowser.open("https://web.whatsapp.com")
        
        # Wait for browser launch
        ProcessManager.wait_for_process(
            WhatsAppUISender.BROWSER_PROCESSES,
            timeout=15
        )
        time.sleep(3)
        return True

    @staticmethod
    def _navigate_to_chat(phone: str):
        """
        Navigate to chat without opening new tab - uses keyboard navigation
        """
        print(f"[WHATSAPP] Navigating to chat: {phone}")
        
        # Focus address bar
        pyautogui.hotkey("ctrl", "l")
        time.sleep(0.3)
        
        # Clear and type URL
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.1)
        
        url = f"https://web.whatsapp.com/send?phone={phone}"
        pyautogui.write(url, interval=0.02)
        time.sleep(0.3)
        
        # Navigate
        pyautogui.press("enter")

    @staticmethod
    def _human_type(text: str, speed: float = 0.03):
        """
        Types message in real-time like a human
        """
        for char in text:
            pyautogui.write(char)
            time.sleep(speed)

    @staticmethod
    def send(phone: str, message: str, load_wait: int = 10):
        """
        UI automation based WhatsApp sender

        phone: countrycode + number (no +)
        example: 97798xxxxxxx
        """

        # Ensure browser is ready
        WhatsAppUISender._open_or_focus_browser()

        # Navigate to chat (reuses existing tab if WhatsApp Web is open)
        WhatsAppUISender._navigate_to_chat(phone)

        print("[WHATSAPP] Waiting for chat to load...")
        time.sleep(load_wait)

        # Click center to ensure focus on message box
        screen = pyautogui.size()
        pyautogui.click(screen.width // 2, screen.height // 2)
        time.sleep(0.5)

        # Clear text box if something exists
        pyautogui.hotkey("ctrl", "a")
        pyautogui.press("backspace")
        time.sleep(0.2)

        # Type message in real time
        print("[WHATSAPP] Typing message...")
        WhatsAppUISender._human_type(message, speed=0.035)

        # Send
        time.sleep(0.4)
        pyautogui.press("enter")

        print("[WHATSAPP] Message sent ✅")

        return {
            "success": True,
            "sent_to": phone,
            "method": "ui-automation",
            "typing": "real-time"
        }