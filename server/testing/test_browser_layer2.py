"""Test Layer 2 - Orchestration with toy adapter.

Prerequisites:
1. Chrome running with remote debugging: chrome.exe --remote-debugging-port=9222
2. Install playwright: pip install playwright && python -m playwright install chromium

Usage:
    python server/testing/test_browser_layer2.py
"""
import asyncio
import sys
from pathlib import Path

# Add server to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from plugins.installed.web.browser.runtime.playwright import PlaywrightRuntime
from plugins.installed.web.browser.state_machine import Flow
from plugins.installed.web.browser.adapters.toy import ToyAdapter
from plugins.installed.web.browser.replay_log import ReplayLog
from plugins.installed.web.browser.events import get_event_bus, BrowserEventType, BrowserEvent
from plugins.installed.web.browser.verification import GoalVerifier


async def test_toy_adapter():
    """Test toy adapter with recovery and state machine."""
    print("=== Layer 2 Test: Toy Adapter with State Machine ===\n")
    
    # Setup
    test_file = Path(__file__).parent.parent / "plugins" / "installed" / "web" / "browser" / "devx" / "fixtures" / "toy_test.html"
    if not test_file.exists():
        print(f"✗ Test file not found: {test_file}")
        return
    
    log_dir = Path(__file__).parent.parent / ".sparkai_data" / "browser_logs"
    replay_log = ReplayLog(log_dir)
    replay_log.start_run("test_layer2_toy")
    
    # Event listener
    events_captured = []
    def on_event(event: BrowserEvent):
        events_captured.append(event)
        print(f"[EVENT] {event.type.value}: {event.data.get('detail', event.data)}")
    
    bus = get_event_bus()
    for event_type in BrowserEventType:
        bus.subscribe(event_type, on_event)
    
    # Connect
    runtime = PlaywrightRuntime(dry_run=False)
    print("Connecting to Chrome...")
    try:
        await runtime.connect()
        print("✓ Connected\n")
    except Exception as e:
        print(f"✗ Failed: {e}")
        return
    
    try:
        page = await runtime.new_page()
        
        # Create adapter and flow
        adapter = ToyAdapter(str(test_file.absolute()))
        adapter.verifier = GoalVerifier()
        
        flow = Flow(
            adapter=adapter,
            intent="test search",
            run_id="toy_test_1",
            page=page,
            runtime=runtime
        )
        
        print("Running flow...")
        result = await flow.run()
        
        print(f"\n=== Flow Result ===")
        print(f"Success: {result.success}")
        print(f"Final State: {result.state.value}")
        print(f"Context: {result.data}")
        if result.error:
            print(f"Error: {result.error}")
        
        print(f"\n=== Events Captured: {len(events_captured)} ===")
        event_types = [e.type.value for e in events_captured]
        print(f"Event types: {event_types}")
        
        print(f"\n=== Budget Stats ===")
        print(f"Actions: {flow.budget.action_count}/{flow.budget.max_actions}")
        print(f"Duration: {asyncio.get_event_loop().time() - flow.budget.start_time:.1f}s/{flow.budget.max_duration_s}s")
        
        print(f"\n=== Circuit Breaker ===")
        print(f"Tripped: {flow.breaker.tripped}")
        print(f"Streak: {flow.breaker.streak}")
        
        print(f"\nReplay log: {replay_log.current_log}")
        
    finally:
        replay_log.end_run()
        await runtime.disconnect()
        print("\n✓ Test complete")


async def test_recovery():
    """Test recovery engine with cookie banner."""
    print("=== Layer 2 Test: Recovery Engine ===\n")
    
    test_file = Path(__file__).parent.parent / "plugins" / "installed" / "web" / "browser" / "devx" / "fixtures" / "toy_test.html"

    runtime = PlaywrightRuntime(dry_run=False)
    print("Connecting...")
    try:
        await runtime.connect()
    except Exception as e:
        print(f"✗ Failed: {e}")
        return
    
    try:
        from plugins.installed.web.browser.recovery import RecoveryEngine
        from plugins.installed.web.browser.errors import BrowserError, BrowserErrorType
        
        page = await runtime.new_page()
        await page.goto(f"file:///{test_file.absolute()}")
        
        print("Testing cookie banner recovery...")
        
        # Simulate element not found error
        error = BrowserError(
            BrowserErrorType.ELEMENT_NOT_FOUND,
            "Submit button not found (simulated)"
        )
        
        recovery = RecoveryEngine()
        result = await recovery.attempt(page, error, {"state": "search"}, runtime)
        
        print(f"Recovery result: {result.recovered}")
        print(f"Strategy: {result.strategy}")
        print(f"Detail: {result.detail}")
        
        # Check if cookie banner was dismissed
        await asyncio.sleep(1)
        banner_visible = await page.evaluate("() => document.getElementById('cookie-banner').style.display !== 'none'")
        print(f"Cookie banner still visible: {banner_visible}")
        
    finally:
        await runtime.disconnect()
        print("\n✓ Recovery test complete")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--recovery", action="store_true", help="Test recovery only")
    args = parser.parse_args()
    
    if args.recovery:
        asyncio.run(test_recovery())
    else:
        asyncio.run(test_toy_adapter())
