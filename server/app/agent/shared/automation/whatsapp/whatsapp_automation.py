import pyautogui
import pyperclip
import pygetwindow as gw
import time
import os
import sys

# Add the server directory to sys.path for imports to work when running directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))))

from app.agent.shared.utils.process_manager.process_manager import ProcessManager

pyautogui.PAUSE = 0.15

# ── Icon paths relative to this file ──────────────────────
# Structure:
#   app/agent/shared/automation/whatsapp/whatsapp_automation.py  ← this file
#   app/agent/shared/automation/whatsapp/icons/btn_plus.png
#   app/agent/shared/automation/whatsapp/icons/btn_docs.png
#   app/agent/shared/automation/whatsapp/icons/btn_photos.png
#   app/agent/shared/automation/whatsapp/icons/btn_call_icon.png
#   app/agent/shared/automation/whatsapp/icons/btn_audio_call.png
#   app/agent/shared/automation/whatsapp/icons/btn_video_call.png

ICONS_DIR = os.path.join(os.path.dirname(__file__), "icons")

def icon(name: str) -> str:
    """Returns absolute path to an icon file"""
    return os.path.join(ICONS_DIR, name)


class WhatsAppAutomation:
    """
    Automates WhatsApp Desktop app using image recognition + keyboard/mouse control.
    Requires WhatsApp Desktop to be already open.

    Usage:
        wa = WhatsAppAutomation()
        wa.send_message("Kartik", "Hey!")
        wa.send_file("Kartik", r"C:/path/to/file.pdf", caption="Here!")
        wa.send_photo("Kartik", r"C:/path/to/photo.jpg", caption="Look!")
        wa.audio_call("Kartik")
        wa.video_call("Kartik")
    """

    def __init__(self, confidence: float = 0.8, search_timeout: int = 3):
        self.confidence     = confidence
        self.search_timeout = search_timeout
        self.process_manager = ProcessManager()

    # ══════════════════════════════════════════════════════
    #  PRIVATE HELPERS
    # ══════════════════════════════════════════════════════

    def _get_window(self):
        """Find and focus the WhatsApp Desktop window"""
        self.process_manager.bring_to_focus("WhatsApp")
        windows = gw.getWindowsWithTitle("WhatsApp")
        if not windows:
            raise RuntimeError("❌ WhatsApp Desktop is not open!")
        win = windows[0]
        win.activate()
        time.sleep(0.5)
        return win

    def _find_button(self, image_path: str) -> tuple | None:
        """Scan screen for a button image, returns center (x, y) or None"""
        start = time.time()
        while time.time() - start < self.search_timeout:
            try:
                loc = pyautogui.locateCenterOnScreen(image_path, confidence=self.confidence)
                if loc:
                    return loc
            except pyautogui.ImageNotFoundException:
                pass
            time.sleep(0.2)
        return None

    def _click_button(self, image_name: str, label: str = "button") -> bool:
        """Find button by icon filename and click it. Returns True if found."""
        path = icon(image_name)
        loc  = self._find_button(path)
        if loc:
            print(f"  ✅ Found [{label}] at {loc} → clicking")
            pyautogui.click(loc)
            return True
        print(f"  ❌ Could not find [{label}] — re-capture {image_name} if this keeps failing")
        return False

    def _open_chat(self, contact_name: str):
        """Search and open a chat by contact name"""
        win = self._get_window()
        wx, wy, ww, wh = win.left, win.top, win.width, win.height

        print(f"  🔍 Opening chat: '{contact_name}'")
        pyautogui.hotkey("ctrl", "f")
        time.sleep(0.5)
        pyautogui.hotkey("ctrl", "a")
        pyperclip.copy(contact_name)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(1.0)

        pyautogui.press("down")   # select first result
        time.sleep(0.3)
        pyautogui.press("enter")  # open chat
        time.sleep(0.8)

        return win

    def _focus_input(self, win):
        """Click the message input box"""
        wx, wy, ww, wh = win.left, win.top, win.width, win.height
        pyautogui.click(wx + int(ww * 0.60), wy + int(wh * 0.95))
        time.sleep(0.3)

    def _paste_and_send(self, text: str):
        """Paste text and press Enter"""
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.2)
        pyautogui.press("enter")

    def _handle_file_dialog(self, file_path: str):
        """Paste file path into OS file dialog and confirm"""
        pyperclip.copy(file_path)
        pyautogui.hotkey("ctrl", "a")
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.4)
        pyautogui.press("enter")
        time.sleep(1.2)  # wait for preview to load

    # ══════════════════════════════════════════════════════
    #  PUBLIC API
    # ══════════════════════════════════════════════════════

    def send_message(self, contact_name: str, message: str):
        """Send a text message to a contact"""
        print(f"\n📨 send_message → '{contact_name}'")
        win = self._open_chat(contact_name)
        self._focus_input(win)
        self._paste_and_send(message)
        print(f"  ✅ Message sent to '{contact_name}'")

    def send_file(self, contact_name: str, file_path: str, caption: str = ""):
        """
        Send any file (PDF, ZIP, DOCX, etc.) to a contact.
        file_path : absolute path to the file e.g. r"C:/Users/You/report.pdf"
        caption   : optional message shown with the file
        """
        print(f"\n📄 send_file → '{contact_name}' | {os.path.basename(file_path)}")
        self._open_chat(contact_name)
        time.sleep(0.3)

        if not self._click_button("btn_plus.png", label="[ + ] button"):
            return
        time.sleep(0.6)

        if not self._click_button("btn_docs.png", label="[ Document ]"):
            return
        time.sleep(1.0)

        self._handle_file_dialog(file_path)

        if caption:
            pyperclip.copy(caption)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.2)

        pyautogui.press("enter")
        print(f"  ✅ File sent to '{contact_name}'")

    def send_photo(self, contact_name: str, photo_path: str, caption: str = ""):
        """
        Send a photo or video to a contact.
        photo_path : absolute path e.g. r"C:/Users/You/photo.jpg"
        caption    : optional message shown with the photo
        """
        print(f"\n🖼️  send_photo → '{contact_name}' | {os.path.basename(photo_path)}")
        self._open_chat(contact_name)
        time.sleep(0.3)

        if not self._click_button("btn_plus.png", label="[ + ] button"):
            return
        time.sleep(0.6)

        if not self._click_button("btn_photos.png", label="[ Photos & Videos ]"):
            return
        time.sleep(1.0)

        self._handle_file_dialog(photo_path)

        if caption:
            pyperclip.copy(caption)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.2)

        pyautogui.press("enter")
        print(f"  ✅ Photo/Video sent to '{contact_name}'")

    def audio_call(self, contact_name: str):
        """
        Start an audio call with a contact.
        Flow: open chat → click 📞 call icon → click [ Audio Call ] in dropdown
        """
        print(f"\n📞 audio_call → '{contact_name}'")
        self._open_chat(contact_name)
        time.sleep(0.5)

        if not self._click_button("btn_call_icon.png", label="[ 📞 call icon ]"):
            return
        time.sleep(0.6)

        if not self._click_button("btn_audio_call.png", label="[ Audio Call ]"):
            return

        print(f"  ✅ Audio call started with '{contact_name}'")

    def video_call(self, contact_name: str):
        """
        Start a video call with a contact.
        Flow: open chat → click 📞 call icon → click [ Video Call ] in dropdown
        """
        print(f"\n📹 video_call → '{contact_name}'")
        self._open_chat(contact_name)
        time.sleep(0.5)

        if not self._click_button("btn_call_icon.png", label="[ 📞 call icon ]"):
            return
        time.sleep(0.6)

        if not self._click_button("btn_video_call.png", label="[ Video Call ]"):
            return

        print(f"  ✅ Video call started with '{contact_name}'")


# ── USAGE ─────────────────────────────────────────────────
if __name__ == "__main__":
    wa = WhatsAppAutomation()

    wa.send_message("Kartik", "Hey! Automated message 🤖")
    wa.send_file("Kartik",    r"C:\Users\Aanand\OneDrive\Desktop\Chromoverse_Vyoma.pdf", caption="Here's the file!")
    wa.send_photo("Kartik",   r"C:\Users\Aanand\OneDrive\Desktop\blob.jpg",              caption="Check this out!")
    wa.audio_call("Kartik")
    wa.video_call("Kartik")