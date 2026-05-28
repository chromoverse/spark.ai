"""Helper script to start Chrome with remote debugging for browser agent tests.

Usage:
    python server/testing/start_chrome_debug.py
    
Then in another terminal:
    python server/testing/test_browser_action_integration.py --test play_media
"""
import subprocess
import sys
import time
import os
from pathlib import Path

def find_chrome():
    """Find Chrome executable on Windows."""
    possible_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            return path
    
    return None

def is_chrome_running():
    """Check if Chrome is already running with debugging."""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', 9222))
    sock.close()
    return result == 0

def start_chrome_debug():
    """Start Chrome with remote debugging enabled."""
    
    # Check if already running
    if is_chrome_running():
        print("✓ Chrome is already running with remote debugging on port 9222")
        print("\nYou can now run tests:")
        print("  python server/testing/test_browser_action_integration.py --test play_media")
        return True
    
    # Find Chrome
    chrome_path = find_chrome()
    if not chrome_path:
        print("✗ Chrome not found!")
        print("\nPlease install Chrome or manually start it with:")
        print('  chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\\temp\\chrome-debug"')
        return False
    
    print(f"Found Chrome: {chrome_path}")
    
    # Create temp user data dir
    user_data_dir = Path.home() / ".chrome-debug-profile"
    user_data_dir.mkdir(exist_ok=True)
    
    print(f"Using profile: {user_data_dir}")
    print("\nStarting Chrome with remote debugging...")
    
    # Start Chrome
    cmd = [
        chrome_path,
        "--remote-debugging-port=9222",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank"
    ]
    
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Wait for Chrome to start
        print("Waiting for Chrome to start", end="", flush=True)
        for i in range(10):
            time.sleep(1)
            print(".", end="", flush=True)
            if is_chrome_running():
                print(" ✓")
                print("\n✓ Chrome started successfully!")
                print(f"✓ Remote debugging available at http://localhost:9222")
                print("\nYou can now run tests:")
                print("  python server/testing/test_browser_action_integration.py --test play_media")
                print("  python server/testing/test_browser_layer1.py")
                print("  python server/testing/test_browser_layer3.py")
                print("\nTo stop Chrome, just close the browser window.")
                return True
        
        print(" ✗")
        print("\n✗ Chrome started but debugging port not available")
        print("Try manually: chrome.exe --remote-debugging-port=9222")
        return False
        
    except Exception as e:
        print(f"\n✗ Failed to start Chrome: {e}")
        print("\nTry manually:")
        print('  chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\\temp\\chrome-debug"')
        return False

if __name__ == "__main__":
    print("="*60)
    print("Chrome Remote Debugging Starter")
    print("="*60)
    print()
    
    success = start_chrome_debug()
    
    if not success:
        sys.exit(1)
