"""
CinebyAutomation — search and play movies on cineby.gd
Combines Selenium (navigation) + pyautogui (clicking)

INSTALL:
    pip install selenium webdriver-manager pyautogui pyperclip

RUN:
    py cineby_automation.py
"""

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import subprocess
import urllib.request
import os
import time
import pyautogui
import pyperclip

# ── Config ─────────────────────────────────────────────────────────────
DEBUG_PORT   = 9222
BASE_URL     = "https://www.cineby.gd"
CHROME_PATH  = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE_DIR  = r"C:\chrome_debug_session"

pyautogui.PAUSE = 0.1


# ══════════════════════════════════════════════════════════════════════
#  CHROME SETUP
# ══════════════════════════════════════════════════════════════════════

def kill_chrome():
    print("🔴 Killing Chrome...")
    os.system("taskkill /f /im chrome.exe >nul 2>&1")
    time.sleep(2)

def launch_chrome():
    print("🚀 Launching Chrome with debug port...")
    subprocess.Popen([
        CHROME_PATH,
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={PROFILE_DIR}",
        "--start-maximized",
        "--no-first-run",
        "--no-default-browser-check",
        BASE_URL
    ])
    # Poll until Chrome responds on debug port
    print("   Waiting", end="", flush=True)
    for _ in range(20):
        time.sleep(1)
        print(".", end="", flush=True)
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json", timeout=1)
            print(" ✅ Chrome ready!\n")
            return
        except Exception:
            continue
    raise RuntimeError("❌ Chrome failed to start in time")

def connect_selenium():
    opt = Options()
    opt.add_experimental_option("debuggerAddress", f"127.0.0.1:{DEBUG_PORT}")
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=opt
    )
    return driver


# ══════════════════════════════════════════════════════════════════════
#  CINEBY AUTOMATION CLASS
# ══════════════════════════════════════════════════════════════════════

class CinebyAutomation:
    """
    Usage:
        bot = CinebyAutomation()
        bot.search_and_play("Inception")
        bot.play_movie_by_id(671)
    """

    def __init__(self):
        print("─" * 50)
        print("  CINEBY AUTOMATION")
        print("─" * 50 + "\n")
        kill_chrome()
        launch_chrome()
        self.driver = connect_selenium()
        time.sleep(2)
        print("✅ Connected!\n")

    # ── URL helpers ────────────────────────────────────────────────────

    def _current_url(self) -> str:
        try:
            return self.driver.execute_script("return window.location.href") or ""
        except Exception:
            return ""

    def _go(self, url: str):
        """Navigate and wait until browser actually lands on the page — no about:blank"""
        print(f"  🌐 Navigating → {url}")
        self.driver.get(url)

        # Poll until URL is no longer blank/about
        deadline = time.time() + 12
        while time.time() < deadline:
            cur = self._current_url()
            if cur and "about:blank" not in cur and "about" not in cur:
                print(f"  ✅ Landed on: {cur}")
                break
            time.sleep(0.4)

        time.sleep(2)  # React render settle
        self.driver.execute_script("window.focus()")

    def _wait_url_change(self, from_url: str, timeout: int = 10) -> str:
        """Wait until URL changes away from from_url — means navigation happened"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            cur = self._current_url()
            if cur and cur != from_url and "about:blank" not in cur:
                print(f"  📄 Navigated to: {cur}")
                return cur
            time.sleep(0.4)
        print("  ⚠️  URL did not change — page may not have reacted to click")
        return self._current_url()

    # ── Window helpers ─────────────────────────────────────────────────

    def _win(self) -> dict:
        """Get Chrome window screen position and size"""
        return self.driver.execute_script("""
            return {
                x: window.screenX,
                y: window.screenY,
                w: window.outerWidth,
                h: window.outerHeight
            }
        """)

    def _click_at(self, rx: float, ry: float, label: str = ""):
        """Click at relative position (0.0–1.0) within Chrome window"""
        w = self._win()
        x = w['x'] + int(w['w'] * rx)
        y = w['y'] + int(w['h'] * ry)
        if label:
            print(f"  🖱️  Clicking {label} at ({x}, {y})")
        pyautogui.click(x, y)

    # ── Public API ─────────────────────────────────────────────────────
    def search_and_play(self, query: str):
      print(f"🎬 search_and_play: '{query}'\n")

      # Step 1: Go to search page
      self._go(f"{BASE_URL}/search")

      # Step 2: Try clicking search box at multiple Y positions
      focused = False
      for ry in [0.25, 0.30, 0.35, 0.40, 0.45]:
          self._click_at(0.50, ry, label=f"search box (ry={ry})")
          time.sleep(0.4)
          # Type one char and see if page reacts
          pyautogui.press("a")
          time.sleep(0.3)
          pyautogui.hotkey("ctrl", "a")
          pyautogui.press("delete")
          time.sleep(0.3)
          # Check if an input is active via JS
          active_tag = self.driver.execute_script("return document.activeElement.tagName")
          print(f"    Active element: {active_tag}")
          if active_tag in ("INPUT", "TEXTAREA"):
              print(f"  ✅ Search box focused at ry={ry}!")
              focused = True
              break

      if not focused:
          print("  ⚠️  Could not focus search box — trying Tab navigation...")
          pyautogui.hotkey("ctrl", "l")  # focus address bar
          time.sleep(0.3)
          pyautogui.press("escape")
          time.sleep(0.3)
          # Tab into the page to find first input
          for _ in range(10):
              pyautogui.press("tab")
              time.sleep(0.2)
              tag = self.driver.execute_script("return document.activeElement.tagName")
              if tag in ("INPUT", "TEXTAREA"):
                  print("  ✅ Found input via Tab!")
                  break

      # Step 3: Type query — results auto-appear
      pyperclip.copy(query)
      pyautogui.hotkey("ctrl", "v")
      print(f"  ⌨️  Typed: '{query}'")
      time.sleep(3)  # wait for auto-fetch

      # Step 4: Use keyboard to select first result — no coordinate guessing
      before = self._current_url()
      pyautogui.press("tab")    # move focus into results
      time.sleep(0.3)
      pyautogui.press("enter")  # open first result
      time.sleep(0.5)

      # Step 5: Wait for movie page
      landed = self._wait_url_change(from_url=before, timeout=10)
      time.sleep(1.5)

      if "/movie/" in landed or "/tv/" in landed:
          print(f"  🎯 On movie page!")
          self._click_play()
      else:
          print(f"  ⚠️  Unexpected URL: {landed}")
          print("      Try bot.play_movie_by_id(671) as fallback")
      def play_movie_by_id(self, movie_id: int):
          """Directly open and play a movie by its cineby ID"""
          print(f"\n▶️  play_movie_by_id: {movie_id}")
          self._go(f"{BASE_URL}/movie/{movie_id}")
          self._click_play()

    def _click_play(self):
        """Click the play button — JS first, Space as fallback"""
        print("  ▶️  Clicking play button...")

        # Try JS click on known play selectors
        js_selectors = [
            "button[aria-label*='Play']",
            "button[aria-label*='play']",
            "[class*='play-button']",
            "[class*='PlayButton']",
            "[class*='play']",
            "button",   # last resort — first button on page
        ]
        for sel in js_selectors:
            try:
                clicked = self.driver.execute_script(f"""
                    var el = document.querySelector("{sel}");
                    if (el) {{ el.click(); return true; }}
                    return false;
                """)
                if clicked:
                    print(f"  ✅ Play clicked via JS ({sel})")
                    time.sleep(0.5)
                    return
            except Exception:
                continue

        # Fallback: click center of screen + Space (works on most video players)
        print("  ⚠️  JS click failed — trying center click + Space")
        self._click_at(0.50, 0.50, label="play center")
        time.sleep(0.5)
        pyautogui.press("space")
        print("  ✅ Space pressed!")


# ══════════════════════════════════════════════════════════════════════
#  RUN
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    bot = CinebyAutomation()

    # Search by name → auto-play first result
    bot.search_and_play("Inception")

    # OR: play directly by movie ID
    # bot.play_movie_by_id(671)