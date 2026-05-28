"""Test Layer 1 - Google search end-to-end with dry-run mode.

Prerequisites:
1. Chrome running with remote debugging: chrome.exe --remote-debugging-port=9222
2. Install playwright: pip install playwright
3. Run: python -m playwright install chromium

Usage:
    python server/testing/test_browser_layer1.py
"""
import asyncio
import sys
from pathlib import Path

# Add server to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from plugins.installed.web.browser.runtime.playwright import PlaywrightRuntime
from plugins.installed.web.browser.semantic import goto, click_by_text, fill_form
from plugins.installed.web.browser.replay_log import ReplayLog
from plugins.installed.web.browser.events import get_event_bus, BrowserEventType, BrowserEvent


async def test_google_search_dry_run():
    """Test Google search flow in dry-run mode."""
    print("=== Layer 1 Test: Google Search (Dry-Run) ===\n")
    
    # Setup replay log
    log_dir = Path(__file__).parent.parent / ".sparkai_data" / "browser_logs"
    replay_log = ReplayLog(log_dir)
    replay_log.start_run("test_layer1_google")
    
    # Setup event listener
    def on_event(event: BrowserEvent):
        print(f"[EVENT] {event.type.value}: {event.data}")
    
    bus = get_event_bus()
    for event_type in BrowserEventType:
        bus.subscribe(event_type, on_event)
    
    # Connect to browser
    runtime = PlaywrightRuntime(dry_run=True)
    print("Connecting to Chrome at localhost:9222...")
    try:
        await runtime.connect()
        print("✓ Connected\n")
    except Exception as e:
        print(f"✗ Failed to connect: {e}")
        print("\nMake sure Chrome is running with:")
        print("  chrome.exe --remote-debugging-port=9222")
        return
    
    try:
        # Get or create page
        pages = await runtime.pages()
        if pages:
            page = pages[0]
            print(f"Using existing page: {page.url}\n")
        else:
            page = await runtime.new_page()
            print("Created new page\n")
        
        # Test 1: Navigate to Google
        print("Test 1: Navigate to Google")
        result = await goto(page, "https://www.google.com", runtime)
        print(f"  Result: ok={result.ok}, confidence={result.confidence:.2f}")
        if result.evidence:
            print(f"  Evidence: {result.evidence}")
        print()
        
        # Test 2: Fill search box
        print("Test 2: Fill search box")
        result = await fill_form(page, {"Search": "playwright automation"}, runtime)
        print(f"  Result: ok={result.ok}, confidence={result.confidence:.2f}")
        if result.evidence:
            print(f"  Evidence: {result.evidence}")
        print()
        
        # Test 3: Click search button
        print("Test 3: Click search button")
        result = await click_by_text(page, "Google Search", runtime)
        print(f"  Result: ok={result.ok}, confidence={result.confidence:.2f}")
        if result.evidence:
            print(f"  Evidence: {result.evidence}")
        print()
        
        # Test 4: Check browser health
        print("Test 4: Browser health check")
        is_alive = await runtime.is_alive()
        print(f"  Browser alive: {is_alive}")
        print()
        
        print("=== All tests completed ===")
        print(f"Replay log: {replay_log.current_log}")
        
    finally:
        replay_log.end_run()
        await runtime.disconnect()
        print("\n✓ Disconnected")


async def test_google_search_real():
    """Test Google search flow in real mode (actually performs actions)."""
    print("=== Layer 1 Test: Google Search (Real Mode) ===\n")
    print("WARNING: This will actually perform actions in your browser!\n")
    
    # Setup replay log
    log_dir = Path(__file__).parent.parent / ".sparkai_data" / "browser_logs"
    replay_log = ReplayLog(log_dir)
    replay_log.start_run("test_layer1_google_real")
    
    # Connect to browser
    runtime = PlaywrightRuntime(dry_run=False)
    print("Connecting to Chrome at localhost:9222...")
    try:
        await runtime.connect()
        print("✓ Connected\n")
    except Exception as e:
        print(f"✗ Failed to connect: {e}")
        return
    
    try:
        page = await runtime.new_page()
        
        # Navigate to Google
        print("Navigating to Google...")
        result = await goto(page, "https://www.google.com", runtime)
        print(f"  ✓ Navigated (confidence: {result.confidence:.2f})\n")
        
        await asyncio.sleep(1)
        
        # Fill search
        print("Filling search box...")
        result = await fill_form(page, {"q": "playwright automation"}, runtime)
        print(f"  ✓ Filled (confidence: {result.confidence:.2f})\n")
        
        await asyncio.sleep(1)
        
        # Click search
        print("Clicking search button...")
        result = await click_by_text(page, "Google Search", runtime)
        print(f"  ✓ Clicked (confidence: {result.confidence:.2f})\n")
        
        await asyncio.sleep(2)
        
        print("=== Test completed ===")
        print(f"Replay log: {replay_log.current_log}")
        
    finally:
        replay_log.end_run()
        await runtime.disconnect()
        print("\n✓ Disconnected")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true", help="Run in real mode (not dry-run)")
    args = parser.parse_args()
    
    if args.real:
        asyncio.run(test_google_search_real())
    else:
        asyncio.run(test_google_search_dry_run())
