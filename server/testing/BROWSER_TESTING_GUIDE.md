# Browser Agent Testing Guide

## Quick Start

### 1. Start Chrome with Remote Debugging
```bash
python server/testing/start_chrome_debug.py
```

This will:
- Find Chrome on your system
- Start it with remote debugging on port 9222
- Create a separate profile so it doesn't interfere with your normal Chrome

### 2. Run Tests
```bash
# Test browser_action integration
python server/testing/test_browser_action_integration.py --test play_media

# Test all browser_action features
python server/testing/test_browser_action_integration.py

# Quick smoke test
python server/testing/test_browser_action_integration.py --quick

# Test individual layers
python server/testing/test_browser_layer1.py
python server/testing/test_browser_layer2.py
python server/testing/test_browser_layer3.py
python server/testing/test_browser_layer4.py
```

---

## What You Just Saw

Your test output shows **the fallback is working perfectly**:

```
⚠ Fell back to URL open (BrowserAgentTool not available)
```

This means:
1. ✅ browser_action tried to use BrowserAgentTool (automation)
2. ✅ Chrome wasn't running with debugging, so it failed
3. ✅ Gracefully fell back to opening URL in browser
4. ✅ User still got their video - just manually instead of automated

**This is the correct behavior!** The system is resilient.

---

## To Enable Full Automation

Run the helper script first:
```bash
python server/testing/start_chrome_debug.py
```

Then run the test again:
```bash
python server/testing/test_browser_action_integration.py --test play_media
```

You should see:
```
✓ Successfully automated via BrowserAgentTool!
```

---

## Test Options

### browser_action integration tests:
```bash
--quick              # Quick smoke test
--test play_media    # Test play_media automation
--test entity        # Test with web_research entity
--test open_url      # Test URL opening
--test book_hotel    # Test hotel booking stub
--test buy_product   # Test product purchase stub
--test invalid       # Test error handling
--test missing       # Test missing params
--test fallback      # Test fallback behavior
```

### Layer tests:
```bash
# Layer 1: Foundation
python server/testing/test_browser_layer1.py
python server/testing/test_browser_layer1.py --real

# Layer 2: Orchestration
python server/testing/test_browser_layer2.py
python server/testing/test_browser_layer2.py --recovery

# Layer 3: Adapters
python server/testing/test_browser_layer3.py
python server/testing/test_browser_layer3.py --dry-run
python server/testing/test_browser_layer3.py --composition

# Layer 4: Hardening
python server/testing/test_browser_layer4.py
python server/testing/test_browser_layer4.py --overlay
python server/testing/test_browser_layer4.py --observers
python server/testing/test_browser_layer4.py --fixtures
python server/testing/test_browser_layer4.py --amazon
```

---

## Troubleshooting

### "ECONNREFUSED ::1:9222"
**Cause:** Chrome not running with remote debugging  
**Fix:** Run `python server/testing/start_chrome_debug.py`

### "Fell back to URL open"
**Cause:** Same as above - Chrome not available  
**Fix:** This is actually correct behavior! The fallback works.  
**To enable automation:** Start Chrome with debugging

### "Playwright not installed"
**Fix:** 
```bash
pip install playwright
python -m playwright install chromium
```

### Chrome won't start
**Manual start:**
```bash
chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\temp\chrome-debug"
```

---

## Expected Results

### With Chrome Running (Full Automation):
```
✓ Successfully automated via BrowserAgentTool!
Data: {'automated': True, 'action': 'play_media', ...}
```

### Without Chrome (Graceful Fallback):
```
⚠ Fell back to URL open (BrowserAgentTool not available)
Data: {'automated': False, 'opened': True, 'url': '...'}
```

**Both are correct!** The system adapts to what's available.

---

## Summary

✅ **Your test worked perfectly** - it showed the fallback behavior  
✅ **To enable automation** - run `start_chrome_debug.py` first  
✅ **System is resilient** - works with or without automation  
✅ **No breaking changes** - existing functionality preserved  

The browser agent gracefully degrades when automation isn't available. This is by design! 🎉
