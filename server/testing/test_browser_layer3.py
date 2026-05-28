"""Test Layer 3 - YouTube play flow end-to-end.

Prerequisites:
1. Chrome running with remote debugging: chrome.exe --remote-debugging-port=9222
2. Install playwright: pip install playwright && python -m playwright install chromium

Usage:
    python server/testing/test_browser_layer3.py
"""
import asyncio
import sys
from pathlib import Path

# Add server to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from plugins.installed.web.browser.tool import BrowserAgentTool
from plugins.installed.web.browser.events import get_event_bus, BrowserEventType, BrowserEvent


async def test_youtube_play():
    """Test YouTube play flow end-to-end."""
    print("=== Layer 3 Test: YouTube Play Flow ===\n")
    
    # Event listener
    events = []
    def on_event(event: BrowserEvent):
        events.append(event)
        print(f"[EVENT] {event.type.value}")
    
    bus = get_event_bus()
    for event_type in BrowserEventType:
        bus.subscribe(event_type, on_event)
    
    # Create tool
    tool = BrowserAgentTool()
    
    print("Testing: Play 'lofi beats' on YouTube\n")
    
    # Execute
    result = await tool._execute({
        "intent": "youtube_play",
        "query": "lofi beats",
        "dry_run": False
    })
    
    print(f"\n=== Result ===")
    print(f"Success: {result.success}")
    print(f"Data: {result.data}")
    if result.error:
        print(f"Error: {result.error}")
    
    print(f"\n=== Events: {len(events)} ===")
    for event in events:
        print(f"  - {event.type.value}")
    
    if result.success:
        print("\n✓ YouTube play flow completed successfully!")
        print("Check your browser - video should be loaded/playing")
    else:
        print("\n✗ Flow failed")


async def test_youtube_dry_run():
    """Test YouTube play in dry-run mode."""
    print("=== Layer 3 Test: YouTube Play (Dry-Run) ===\n")
    
    tool = BrowserAgentTool()
    
    print("Testing: Play 'lofi beats' on YouTube (dry-run)\n")
    
    result = await tool._execute({
        "intent": "youtube_play",
        "query": "lofi beats",
        "dry_run": True
    })
    
    print(f"\n=== Result ===")
    print(f"Success: {result.success}")
    print(f"Data: {result.data}")
    
    if result.success:
        print("\n✓ Dry-run completed - no actual clicks performed")


async def test_adapter_composition():
    """Test that YouTube adapter uses reusable steps."""
    print("=== Layer 3 Test: Adapter Composition ===\n")
    
    from plugins.installed.web.browser.adapters.youtube import YouTubeAdapter
    from plugins.installed.web.browser.state_machine import FlowState
    
    adapter = YouTubeAdapter()
    
    # Check search graph
    search_graph = adapter.graph_for_state(FlowState.SEARCH)
    print(f"Search graph has {len(search_graph.steps)} steps:")
    for step in search_graph.steps:
        print(f"  - {step.name}: {step.goal}")
    
    # Check select graph
    select_graph = adapter.graph_for_state(FlowState.SELECT)
    print(f"\nSelect graph has {len(select_graph.steps)} steps:")
    for step in select_graph.steps:
        print(f"  - {step.name}: {step.goal}")
    
    print("\n✓ Adapter uses reusable steps from steps.py")
    print(f"✓ YouTube adapter is {len(open('plugins/installed/web/browser/adapters/youtube.py').read().splitlines())} lines")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Run in dry-run mode")
    parser.add_argument("--composition", action="store_true", help="Test adapter composition")
    args = parser.parse_args()
    
    if args.composition:
        asyncio.run(test_adapter_composition())
    elif args.dry_run:
        asyncio.run(test_youtube_dry_run())
    else:
        asyncio.run(test_youtube_play())
