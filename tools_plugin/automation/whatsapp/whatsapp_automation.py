import pyautogui
import pyperclip
import pygetwindow as gw
import time
import os
import sys
import builtins

# Add the server directory to sys.path for imports to work when running directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))))

from tools_plugin.tools.system.app import AppOpenTool
from tools_plugin.utils.process_manager.process_manager import ProcessManager

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


def _emit(message: str) -> None:
    """
    Console-safe output helper.
    Falls back to ASCII when terminal codec cannot render unicode glyphs.
    """
    try:
        builtins.print(message)
    except UnicodeEncodeError:
        builtins.print(message.encode("ascii", errors="replace").decode("ascii"))


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
        self.confidence      = confidence
        self.search_timeout  = search_timeout
        self.process_manager = ProcessManager()
        self.app_open_tool   = AppOpenTool()
        

    # ══════════════════════════════════════════════════════
    #  PRIVATE HELPERS
    # ══════════════════════════════════════════════════════

    @classmethod
    async def create(cls, confidence: float = 0.8, search_timeout: int = 3) -> "WhatsAppAutomation":
        """
        Async factory — opens WhatsApp and waits for it to be ready.
        Usage:  wa = await WhatsAppAutomation.create()
        """
        self = cls(confidence=confidence, search_timeout=search_timeout)
        open_result = await self.app_open_tool.execute({"target": "WhatsApp"})
        if not open_result.success:
            raise RuntimeError(f"Failed to open WhatsApp: {open_result.error or 'unknown error'}")
        _emit("  ⏳ Waiting for WhatsApp to be ready...")
        focused = self.process_manager.bring_to_focus("WhatsApp")
        if not focused:
            # Windows can block foreground focus from background threads/processes.
            # Try direct pygetwindow activation as a fallback before failing.
            windows = gw.getWindowsWithTitle("WhatsApp")
            if windows:
                try:
                    win = windows[0]
                    if getattr(win, "isMinimized", False):
                        win.restore()
                        time.sleep(0.2)
                    win.activate()
                    time.sleep(0.4)
                    focused = True
                except Exception:
                    focused = False
            else:
                focused = False
        if not focused:
            _emit("  ⚠️ Could not force WhatsApp to foreground; continuing with best-effort focus")
        time.sleep(3)   # let the app fully render before clicking
        return self

    def _get_window(self):
        """Find and focus the WhatsApp Desktop window"""
        windows = gw.getWindowsWithTitle("WhatsApp")
        if not windows:
            raise RuntimeError("❌ WhatsApp Desktop is not open!")
        win = windows[0]
        try:
            if getattr(win, "isMinimized", False):
                win.restore()
                time.sleep(0.2)
            win.activate()
        except Exception:
            # Fallback: click near title/header area to force focus.
            try:
                pyautogui.click(win.left + int(win.width * 0.5), win.top + 40)
            except Exception as exc:
                raise RuntimeError(f"Failed to focus WhatsApp window: {exc}") from exc
        time.sleep(0.5)
        return win

    def _get_wa_region(self, win):
        """
        Returns (left, top, width, height) of the WhatsApp window.
        Used to restrict OpenCV search to ONLY inside WhatsApp —
        prevents false matches on VS Code tabs, taskbar, browser, etc.
        """
        return (win.left, win.top, win.width, win.height)
    def _find_button(self, image_path: str, confidence: float | None = None, region=None) -> tuple | None:
        conf  = confidence if confidence is not None else self.confidence

        # ── Safety: check needle fits inside region before passing ──
        if region is not None:
            try:
                from PIL import Image
                img = Image.open(image_path)
                nw, nh = img.size
                _, _, rw, rh = region
                if nw > rw or nh > rh:
                    _emit(f"  ⚠️  btn too large ({nw}x{nh}) for region ({rw}x{rh}) → full screen")
                    region = None  # fall back to full screen
            except Exception:
                region = None  # if anything fails, just go full screen

        start = time.time()
        while time.time() - start < self.search_timeout:
            try:
                loc = pyautogui.locateCenterOnScreen(image_path, confidence=conf, region=region)
                if loc:
                    return loc
            except pyautogui.ImageNotFoundException:
                pass
            except ValueError:
                # needle bigger than region — drop region and retry full screen
                _emit(f"  ⚠️  Region too small — retrying full screen...")
                region = None
            time.sleep(0.2)

        # ── Fallback: lower confidence ───────────────────────────────
        if conf > 0.6:
            _emit(f"  ⚠️  Not found at {conf} — retrying at 0.6...")
            try:
                loc = pyautogui.locateCenterOnScreen(image_path, confidence=0.6, region=region)
                if loc:
                    return loc
            except (pyautogui.ImageNotFoundException, ValueError):
                pass

        return None
    def _click_button(self, image_name: str, label: str = "button", confidence: float | None = None, region=None) -> bool:
        """
        Find a button by its icon filename and click it.
        region    : (left, top, w, h) — restrict search area to avoid false matches.
        confidence: override default confidence for this button only.
        Returns True if found and clicked, False otherwise.
        """
        path = icon(image_name)
        loc  = self._find_button(path, confidence=confidence, region=region)
        if loc:
            _emit(f"  ✅ Found [{label}] at {loc} → clicking")
            pyautogui.click(loc)
            return True
        _emit(f"  ❌ Could not find [{label}] — re-capture {image_name} if this keeps failing")
        return False

    def _open_chat(self, contact_name: str):
        """Search and open a chat by contact name. Returns the WhatsApp window."""
        win = self._get_window()

        _emit(f"  🔍 Opening chat: '{contact_name}'")
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
        """Click the message input box at the bottom of the chat"""
        wx, wy, ww, wh = win.left, win.top, win.width, win.height
        pyautogui.click(wx + int(ww * 0.60), wy + int(wh * 0.95))
        time.sleep(0.3)

    def _paste_and_send(self, text: str):
        """Paste text from clipboard and press Enter to send"""
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.2)
        pyautogui.press("enter")

    def _handle_file_dialog(self, file_path: str):
        """Paste a file path into the OS file picker dialog and confirm"""
        pyperclip.copy(file_path)
        pyautogui.hotkey("ctrl", "a")
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.4)
        pyautogui.press("enter")
        time.sleep(1.2)  # wait for WhatsApp preview to load

    # ══════════════════════════════════════════════════════
    #  PUBLIC API
    # ══════════════════════════════════════════════════════

    def send_message(self, contact_name: str, message: str) -> bool:
        """Send a text message to a contact by name"""
        _emit(f"\n📨 send_message → '{contact_name}'")
        win = self._open_chat(contact_name)
        self._focus_input(win)
        self._paste_and_send(message)
        _emit(f"  ✅ Message sent to '{contact_name}'")
        return True

    def send_file(self, contact_name: str, file_path: str, caption: str = "") -> bool:
        """
        Send any file (PDF, ZIP, DOCX, etc.) to a contact.
        file_path : absolute path  e.g. r"C:/Users/You/report.pdf"
        caption   : optional text shown with the file (default: none)
        """
        _emit(f"\n📄 send_file → '{contact_name}' | {os.path.basename(file_path)}")
        win = self._open_chat(contact_name)
        time.sleep(0.3)
        region = self._get_wa_region(win)

        # lower confidence for + button — it changes look based on hover/tooltip state
        if not self._click_button("btn_plus.png", label="[ + ] button", confidence=0.6, region=region):
            raise RuntimeError("Could not find WhatsApp attachment button (+)")
        time.sleep(0.6)

        if not self._click_button("btn_docs.png", label="[ Document ]", region=region):
            raise RuntimeError("Could not find WhatsApp document option")
        time.sleep(1.0)

        self._handle_file_dialog(file_path)

        if caption:
            pyperclip.copy(caption)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.2)

        pyautogui.press("enter")
        _emit(f"  ✅ File sent to '{contact_name}'")
        return True

    def send_photo(self, contact_name: str, photo_path: str, caption: str = "") -> bool:
        """
        Send a photo or video to a contact.
        photo_path : absolute path  e.g. r"C:/Users/You/photo.jpg"
        caption    : optional text shown with the photo (default: none)
        """
        _emit(f"\n🖼️  send_photo → '{contact_name}' | {os.path.basename(photo_path)}")
        win = self._open_chat(contact_name)
        time.sleep(0.3)
        region = self._get_wa_region(win)

        # lower confidence for + button — it changes look based on hover/tooltip state
        if not self._click_button("btn_plus.png", label="[ + ] button", confidence=0.6, region=region):
            raise RuntimeError("Could not find WhatsApp attachment button (+)")
        time.sleep(0.6)

        if not self._click_button("btn_photos.png", label="[ Photos & Videos ]", region=region):
            raise RuntimeError("Could not find WhatsApp photos/videos option")
        time.sleep(1.0)

        self._handle_file_dialog(photo_path)

        if caption:
            pyperclip.copy(caption)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.2)

        pyautogui.press("enter")
        _emit(f"  ✅ Photo/Video sent to '{contact_name}'")
        return True

    def audio_call(self, contact_name: str) -> bool:
        """
        Start a voice call with a contact.
        Flow: open chat → click 📞 call icon → click [ Voice ] in dropdown.
        Dropdown is searched ONLY inside WhatsApp window to avoid false matches.
        """
        _emit(f"\n📞 audio_call → '{contact_name}'")
        win = self._open_chat(contact_name)
        time.sleep(0.5)
        region = self._get_wa_region(win)

        # call icon lives in the chat header — full screen ok
        if not self._click_button("btn_call_icon.png", label="[ 📞 call icon ]"):
            raise RuntimeError("Could not find WhatsApp call icon")
        time.sleep(0.8)  # wait for dropdown to fully appear

        # RESTRICT to WhatsApp window — stops matching VS Code tabs etc.
        if not self._click_button("btn_audio_call.png", label="[ Voice ]", region=region):
            raise RuntimeError("Could not find WhatsApp audio-call menu item")

        _emit(f"  ✅ Audio call started with '{contact_name}'")
        return True

    def video_call(self, contact_name: str) -> bool:
        """
        Start a video call with a contact.
        Flow: open chat → click 📞 call icon → click [ Video ] in dropdown.
        Dropdown is searched ONLY inside WhatsApp window to avoid false matches.
        """
        _emit(f"\n📹 video_call → '{contact_name}'")
        win = self._open_chat(contact_name)
        time.sleep(0.5)
        region = self._get_wa_region(win)

        # call icon lives in the chat header — full screen ok
        if not self._click_button("btn_call_icon.png", label="[ 📞 call icon ]"):
            raise RuntimeError("Could not find WhatsApp call icon")
        time.sleep(0.8)  # wait for dropdown to fully appear

        # RESTRICT to WhatsApp window — stops matching VS Code tabs etc.
        if not self._click_button("btn_video_call.png", label="[ Video ]", region=region):
            raise RuntimeError("Could not find WhatsApp video-call menu item")

        _emit(f"  ✅ Video call started with '{contact_name}'")
        return True


# ── USAGE ─────────────────────────────────────────────────
if __name__ == "__main__":
    wa = WhatsAppAutomation()

    wa.send_message("Kartik", "Hey! Automated message 🤖")
    wa.send_file("Kartik",  r"C:\Users\Aanand\OneDrive\Desktop\Chromoverse_Vyoma.pdf", caption="Here's the file!")
    wa.send_photo("Kartik", r"C:\Users\Aanand\OneDrive\Desktop\blob.jpg",              caption="Check this out!")
    wa.audio_call("Kartik")
    wa.video_call("Kartik")
