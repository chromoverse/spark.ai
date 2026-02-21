
import pyautogui
import time
import os

# ── Config ────────────────────────────────────────────────
SCRIPT_DIR = r"D:\siddhant-files\projects\ai_assistant\ai_local\server"
COUNTDOWN  = 5   # seconds to hover before capture

# ── Core capture function ─────────────────────────────────
def capture(filename, instruction, w=160, h=100):
    print(f"\n  📌 NEXT  →  {instruction}")
    print(f"  Hover your mouse over it and HOLD STILL...")
    print(f"  Capturing in ", end="", flush=True)
    for i in range(COUNTDOWN, 0, -1):
        print(f"{i}... ", end="", flush=True)
        time.sleep(1)
    x, y = pyautogui.position()
    shot = pyautogui.screenshot(region=(x - w//2, y - h//2, w, h))
    path = os.path.join(SCRIPT_DIR, filename)
    shot.save(path)
    print(f"\n  ✅ Saved → {filename}  (center: x={x}, y={y}, size: {w}x{h})\n")

def section(title):
    print("\n" + "─"*55)
    print(f"  {title}")
    print("─"*55)

def pause(msg):
    input(f"\n  ⚡ {msg}\n     Press ENTER when ready...")

# ─────────────────────────────────────────────────────────
#  START
# ─────────────────────────────────────────────────────────
print("\n" + "="*55)
print("   WHATSAPP BUTTON CAPTURE TOOL")
print("   Make sure WhatsApp is open with any chat visible!")
print("="*55)

pause("Open WhatsApp → open any chat (e.g. Kartik) → come back here and press ENTER")


# ════════════════════════════════════════════════════════
#  SECTION 1 — CALL BUTTONS
# ════════════════════════════════════════════════════════
section("SECTION 1 of 3 — CALL BUTTONS (top right of chat)")

# 1a. The call icon in chat header
capture(
    "btn_call_icon.png",
    "Hover on the 📞 PHONE ICON (top right of the chat header bar)",
    w=160, h=100
)

# 1b. Open dropdown → hover Audio Call
pause("Now CLICK the 📞 phone icon to open the dropdown → come back and press ENTER")
capture(
    "btn_audio_call.png",
    "Hover on [ Audio Call ] inside the dropdown menu",
    w=200, h=70
)

# 1c. Open dropdown again → hover Video Call
pause("CLICK the 📞 phone icon AGAIN to reopen dropdown → come back and press ENTER")
capture(
    "btn_video_call.png",
    "Hover on [ Video Call ] inside the dropdown menu",
    w=200, h=70
)


# ════════════════════════════════════════════════════════
#  SECTION 2 — PLUS / ATTACHMENT BUTTON
# ════════════════════════════════════════════════════════
section("SECTION 2 of 3 — ATTACHMENT [ + ] BUTTON (bottom of chat input)")

# 2a. The + button
capture(
    "btn_plus.png",
    "Hover on the [ + ] PLUS / PAPERCLIP button (bottom left of message input bar)",
    w=160, h=100
)

# 2b. Open + menu → hover Documents
pause("Now CLICK the [ + ] button to open the menu → come back and press ENTER")
capture(
    "btn_docs.png",
    "Hover on [ Document ] option inside the popup menu",
    w=220, h=70
)

# 2c. Close menu (press Escape), open again → hover Photos & Videos
pause("Press ESC to close the menu → CLICK [ + ] again to reopen → come back and press ENTER")
capture(
    "btn_photos.png",
    "Hover on [ Photos & Videos ] option inside the popup menu",
    w=220, h=70
)


# ════════════════════════════════════════════════════════
#  SECTION 3 — VERIFY ALL FILES EXIST
# ════════════════════════════════════════════════════════
section("SECTION 3 of 3 — VERIFYING ALL SAVED FILES")

expected = [
    "btn_call_icon.png",
    "btn_audio_call.png",
    "btn_video_call.png",
    "btn_plus.png",
    "btn_docs.png",
    "btn_photos.png",
]

all_good = True
for fname in expected:
    full_path = os.path.join(SCRIPT_DIR, fname)
    if os.path.exists(full_path):
        size = os.path.getsize(full_path)
        print(f"  ✅  {fname}  ({size} bytes)")
    else:
        print(f"  ❌  {fname}  MISSING!")
        all_good = False

print()
if all_good:
    print("  🎉 ALL BUTTONS CAPTURED SUCCESSFULLY!")
    print("  You can now run your main whatsapp automation script.")
else:
    print("  ⚠️  Some buttons are missing — re-run this script and redo those steps.")

print("="*55 + "\n")