"""Test Layer 4 - Hardening & DevX.

Prerequisites:
1. Chrome running with remote debugging: chrome.exe --remote-debugging-port=9222
2. Install playwright: pip install playwright && python -m playwright install chromium

Usage:
    python server/testing/test_browser_layer4.py
"""
import asyncio
import sys
import os
from pathlib import Path

# Add server to path
sys.path.insert(0, str(Path(__file__).parent.parent))


async def test_overlay():
    """Test visual debugging overlay."""
    print("=== Layer 4 Test: Visual Overlay ===\n")
    
    # Enable overlay
    os.environ["BROWSER_DEBUG_OVERLAY"] = "1"
    
    from plugins.installed.web.browser.runtime.playwright import PlaywrightRuntime
    from plugins.installed.web.browser.semantic import click_by_text
    from plugins.installed.web.browser.devx.overlay import highlight_element
    
    test_file = Path(__file__).parent.parent / "plugins" / "installed" / "web" / "browser" / "devx" / "fixtures" / "static_form.html"
    
    runtime = PlaywrightRuntime(dry_run=True)
    print("Connecting...")
    try:
        await runtime.connect()
    except Exception as e:
        print(f"✗ Failed: {e}")
        return
    
    try:
        page = await runtime.new_page()
        await page.goto(f"file:///{test_file.absolute()}")
        
        print("Testing overlay with dry-run mode...")
        print("(Check browser - you should see colored boxes)\n")
        
        # Test click with overlay
        result = await click_by_text(page, "Submit", runtime)
        print(f"Click result: ok={result.ok}, confidence={result.confidence:.2f}")
        
        await asyncio.sleep(2)
        
        # Test manual highlight
        await highlight_element(page, "#name", "Name Input", 0.95, enabled=True)
        await highlight_element(page, "#email", "Email Input", 0.75, enabled=True)
        await highlight_element(page, "#submit-btn", "Submit Button", 0.50, enabled=True)
        
        print("\n✓ Overlay test complete")
        print("Green = high confidence (>0.9)")
        print("Yellow = medium confidence (0.7-0.9)")
        print("Red = low confidence (<0.7)")
        
        await asyncio.sleep(3)
        
    finally:
        await runtime.disconnect()


async def test_observers():
    """Test network and console observers."""
    print("=== Layer 4 Test: Observers ===\n")
    
    from plugins.installed.web.browser.runtime.playwright import PlaywrightRuntime
    from plugins.installed.web.browser.devx.observers import PageObservers
    
    runtime = PlaywrightRuntime(dry_run=False)
    print("Connecting...")
    try:
        await runtime.connect()
    except Exception as e:
        print(f"✗ Failed: {e}")
        return
    
    try:
        page = await runtime.new_page()
        
        # Attach observers
        observers = PageObservers()
        await observers.attach(page)
        
        print("Navigating to example.com...")
        await page.goto("https://example.com")
        
        await asyncio.sleep(2)
        
        print(f"\n=== Observer Results ===")
        print(f"Network events: {len(observers.network_events)}")
        for event in observers.network_events[:5]:
            status = f"HTTP {event.status}" if event.status else "FAILED"
            print(f"  {event.method} {event.url[:50]}... - {status}")
        
        print(f"\nConsole events: {len(observers.console_events)}")
        for event in observers.console_events[:5]:
            print(f"  [{event.type}] {event.text[:50]}")
        
        errors = observers.get_errors()
        print(f"\nConsole errors: {len(errors)}")
        
        failures = await observers.recent_failures(since_s=10.0)
        print(f"Recent failures: {len(failures)}")
        
        idle = await observers.network_idle_for(1.0)
        print(f"Network idle: {idle}")
        
        print("\n✓ Observers test complete")
        
    finally:
        await runtime.disconnect()


async def test_fixtures():
    """Test all fixtures."""
    print("=== Layer 4 Test: Fixtures ===\n")
    
    from plugins.installed.web.browser.runtime.playwright import PlaywrightRuntime
    from plugins.installed.web.browser.perception.dom import wait_dom_stable
    from plugins.installed.web.browser.recovery import RecoveryEngine
    from plugins.installed.web.browser.errors import BrowserError, BrowserErrorType
    
    fixtures_dir = Path(__file__).parent.parent / "plugins" / "installed" / "web" / "browser" / "devx" / "fixtures"
    fixtures = [
        ("static_form.html", "Static form"),
        ("cookie_banner.html", "Cookie banner"),
        ("delayed_render.html", "Delayed render"),
        ("toy_test.html", "Toy test"),
        ("triple_continue.html", "Triple continue (multi-strategy)"),
        ("dead_end.html", "Dead end (verification failure)"),
        ("fake_checkout.html", "Fake checkout (payment handoff)"),
        ("captcha_modal.html", "Captcha modal (human loop)"),
    ]
    
    runtime = PlaywrightRuntime(dry_run=False)
    print("Connecting...")
    try:
        await runtime.connect()
    except Exception as e:
        print(f"✗ Failed: {e}")
        return
    
    try:
        page = await runtime.new_page()
        
        for filename, desc in fixtures:
            filepath = fixtures_dir / filename
            if not filepath.exists():
                print(f"⊘ {desc}: file not found")
                continue
            
            print(f"\nTesting {desc}...")
            await page.goto(f"file:///{filepath.absolute()}")
            
            # Test DOM stability
            stable = await wait_dom_stable(page, settle_ms=500, timeout_s=5.0)
            print(f"  DOM stable: {stable}")
            
            # Test recovery on cookie banner
            if "cookie" in filename:
                recovery = RecoveryEngine()
                error = BrowserError(
                    BrowserErrorType.ELEMENT_NOT_FOUND,
                    "Test error"
                )
                result = await recovery.attempt(page, error, {"state": "test"}, runtime)
                print(f"  Recovery: {result.recovered} ({result.strategy})")
        
        print("\n✓ All fixtures tested")
        
    finally:
        await runtime.disconnect()


async def test_amazon_adapter():
    """Test Amazon adapter (dry-run only)."""
    print("=== Layer 4 Test: Amazon Adapter (Dry-Run) ===\n")
    
    from plugins.installed.web.browser.tool import BrowserAgentTool
    
    tool = BrowserAgentTool()
    
    print("Testing: Add 'wireless mouse' to Amazon cart (dry-run)\n")
    
    result = await tool._execute({
        "intent": "buy_product",
        "query": "wireless mouse",
        "dry_run": True
    })
    
    print(f"\n=== Result ===")
    print(f"Success: {result.success}")
    print(f"Data: {result.data}")
    if result.error:
        print(f"Error: {result.error}")
    
    if result.success:
        print("\n✓ Amazon adapter dry-run completed")
        print("Note: Real Amazon flow requires manual testing")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--overlay", action="store_true", help="Test overlay")
    parser.add_argument("--observers", action="store_true", help="Test observers")
    parser.add_argument("--fixtures", action="store_true", help="Test fixtures")
    parser.add_argument("--amazon", action="store_true", help="Test Amazon adapter")
    args = parser.parse_args()
    
    if args.overlay:
        asyncio.run(test_overlay())
    elif args.observers:
        asyncio.run(test_observers())
    elif args.fixtures:
        asyncio.run(test_fixtures())
    elif args.amazon:
        asyncio.run(test_amazon_adapter())
    else:
        print("Running all Layer 4 tests...\n")
        asyncio.run(test_fixtures())
        print("\n" + "="*50 + "\n")
        asyncio.run(test_overlay())
