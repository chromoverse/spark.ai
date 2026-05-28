"""Test browser_action.py integration with BrowserAgentTool.

This tests that the existing browser_action tool correctly delegates to
BrowserAgentTool for automated flows and falls back gracefully.

Prerequisites:
1. Chrome running: chrome.exe --remote-debugging-port=9222
2. Playwright installed: pip install playwright && python -m playwright install chromium

Usage:
    python server/testing/test_browser_action_integration.py
"""
import asyncio
import sys
from pathlib import Path

# Add server to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from plugins.installed.web.tools.browser_action import BrowserActionTool


async def test_play_media_automation():
    """Test play_media delegates to BrowserAgentTool."""
    print("=== Test: play_media with automation ===\n")
    
    tool = BrowserActionTool()
    
    print("Testing: Play 'lofi beats' via browser_action")
    print("Expected: Should delegate to BrowserAgentTool\n")
    
    result = await tool._execute({
        "action": "play_media",
        "title": "lofi beats"
    })
    
    print(f"Success: {result.success}")
    print(f"Data: {result.data}")
    
    if result.success:
        automated = result.data.get("automated", False)
        if automated:
            print("\n✓ Successfully automated via BrowserAgentTool!")
        else:
            print("\n⚠ Fell back to URL open (BrowserAgentTool not available)")
            print("\nTo enable automation:")
            print("  1. Run: python server/testing/start_chrome_debug.py")
            print("  2. Then run this test again")
    else:
        print(f"\n✗ Failed: {result.error}")
    
    return result.success


async def test_play_media_with_entity():
    """Test play_media with entity from web_research."""
    print("\n=== Test: play_media with entity ===\n")
    
    tool = BrowserActionTool()
    
    # Simulate entity from web_research
    entity = {
        "name": "Interstellar Soundtrack",
        "type": "video",
        "source": "youtube"
    }
    
    print(f"Testing: Play entity '{entity['name']}'")
    
    result = await tool._execute({
        "action": "play_media",
        "entity": entity
    })
    
    print(f"Success: {result.success}")
    print(f"Automated: {result.data.get('automated', False)}")
    
    return result.success


async def test_open_url():
    """Test open_url action."""
    print("\n=== Test: open_url ===\n")
    
    tool = BrowserActionTool()
    
    print("Testing: Open YouTube homepage")
    
    result = await tool._execute({
        "action": "open_url",
        "url": "https://www.youtube.com"
    })
    
    print(f"Success: {result.success}")
    print(f"Opened: {result.data.get('opened', False)}")
    
    return result.success


async def test_book_hotel_stub():
    """Test book_hotel stub (should open URL)."""
    print("\n=== Test: book_hotel stub ===\n")
    
    tool = BrowserActionTool()
    
    entity = {
        "name": "Grand Hotel",
        "booking_url": "https://www.booking.com/hotel/grand"
    }
    
    print(f"Testing: Book hotel '{entity['name']}'")
    print("Expected: Opens booking URL (no adapter yet)\n")
    
    result = await tool._execute({
        "action": "book_hotel",
        "entity": entity
    })
    
    print(f"Success: {result.success}")
    print(f"Automated: {result.data.get('automated', False)}")
    print(f"Message: {result.data.get('message', '')}")
    
    return result.success


async def test_buy_product_stub():
    """Test buy_product stub."""
    print("\n=== Test: buy_product stub ===\n")
    
    tool = BrowserActionTool()
    
    entity = {
        "name": "Wireless Mouse",
        "buy_url": "https://www.amazon.com/dp/B08XYZ"
    }
    
    print(f"Testing: Buy product '{entity['name']}'")
    
    result = await tool._execute({
        "action": "buy_product",
        "entity": entity
    })
    
    print(f"Success: {result.success}")
    print(f"Message: {result.data.get('message', '')}")
    
    return result.success


async def test_invalid_action():
    """Test invalid action handling."""
    print("\n=== Test: invalid action ===\n")
    
    tool = BrowserActionTool()
    
    print("Testing: Invalid action 'invalid_action'")
    
    result = await tool._execute({
        "action": "invalid_action"
    })
    
    print(f"Success: {result.success}")
    print(f"Error: {result.error}")
    
    # Should fail gracefully
    return not result.success  # Success = it failed correctly


async def test_missing_params():
    """Test missing required parameters."""
    print("\n=== Test: missing parameters ===\n")
    
    tool = BrowserActionTool()
    
    print("Testing: play_media without title or entity")
    
    result = await tool._execute({
        "action": "play_media"
        # Missing title and entity
    })
    
    print(f"Success: {result.success}")
    if not result.success:
        print(f"Error: {result.error}")
    else:
        print(f"Reason: {result.data.get('reason', '')}")
    
    # Should handle gracefully
    return True


async def test_fallback_behavior():
    """Test that fallback works when BrowserAgentTool fails."""
    print("\n=== Test: fallback behavior ===\n")
    
    tool = BrowserActionTool()
    
    print("Testing: Play with garbage query (should fall back to URL open)")
    
    result = await tool._execute({
        "action": "play_media",
        "title": "xyzabc123nonexistent"
    })
    
    print(f"Success: {result.success}")
    print(f"Automated: {result.data.get('automated', False)}")
    print(f"URL: {result.data.get('url', 'N/A')}")
    
    # Should succeed with fallback
    return result.success


async def run_all_tests():
    """Run all integration tests."""
    print("="*60)
    print("BROWSER ACTION INTEGRATION TESTS")
    print("="*60)
    print()
    
    tests = [
        ("play_media automation", test_play_media_automation),
        ("play_media with entity", test_play_media_with_entity),
        ("open_url", test_open_url),
        ("book_hotel stub", test_book_hotel_stub),
        ("buy_product stub", test_buy_product_stub),
        ("invalid action", test_invalid_action),
        ("missing params", test_missing_params),
        ("fallback behavior", test_fallback_behavior),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            success = await test_func()
            results.append((name, success))
        except Exception as e:
            print(f"\n✗ Test '{name}' crashed: {e}")
            results.append((name, False))
        
        await asyncio.sleep(1)  # Brief pause between tests
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for name, success in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"{status}: {name}")
    
    print(f"\nTotal: {passed}/{total} passed")
    
    if passed == total:
        print("\n🎉 All tests passed!")
    else:
        print(f"\n⚠ {total - passed} test(s) failed")
    
    return passed == total


async def test_quick():
    """Quick smoke test - just play_media."""
    print("=== Quick Smoke Test ===\n")
    
    tool = BrowserActionTool()
    
    print("Testing: play_media('lofi beats')")
    
    result = await tool._execute({
        "action": "play_media",
        "title": "lofi beats"
    })
    
    print(f"\nSuccess: {result.success}")
    print(f"Automated: {result.data.get('automated', False)}")
    print(f"Message: {result.data.get('message', '')}")
    
    if result.success:
        print("\n✓ browser_action integration working!")
    else:
        print(f"\n✗ Failed: {result.error}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="Run quick smoke test only")
    parser.add_argument("--test", choices=[
        "play_media", "entity", "open_url", "book_hotel", 
        "buy_product", "invalid", "missing", "fallback"
    ], help="Run specific test")
    args = parser.parse_args()
    
    if args.quick:
        asyncio.run(test_quick())
    elif args.test:
        test_map = {
            "play_media": test_play_media_automation,
            "entity": test_play_media_with_entity,
            "open_url": test_open_url,
            "book_hotel": test_book_hotel_stub,
            "buy_product": test_buy_product_stub,
            "invalid": test_invalid_action,
            "missing": test_missing_params,
            "fallback": test_fallback_behavior,
        }
        asyncio.run(test_map[args.test]())
    else:
        asyncio.run(run_all_tests())
